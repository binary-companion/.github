"""The real GitHub layer: GraphQL through the `gh` CLI (GH_TOKEN must be an App installation token)."""

from __future__ import annotations

import json
import subprocess

from model import Issue, Item, Project

_ITEMS = """projectItems(first: 20) { nodes { id project { id }
  fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } } }"""
_ISSUE_FIELDS = f"""id number closed repository {{ nameWithOwner }}
  parent {{ number repository {{ nameWithOwner }} }} {_ITEMS}"""


def _gql(query: str, **variables) -> dict:
    cmd = ["gh", "api", "graphql", "-H", "GraphQL-Features: sub_issues", "-f", f"query={query}"]
    for k, v in variables.items():
        cmd += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def _issue(node: dict) -> Issue:
    parent = node.get("parent")
    return Issue(
        id=node["id"], repo=node["repository"]["nameWithOwner"], number=node["number"], closed=node["closed"],
        parent=(parent["repository"]["nameWithOwner"], parent["number"]) if parent else None,
        items=[Item(n["id"], n["project"]["id"], (n["fieldValueByName"] or {}).get("name"))
               for n in node["projectItems"]["nodes"]],
    )


class GH:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._status: dict[str, tuple[str, dict[str, str]]] = {}

    def issue(self, repo: str, number: int) -> Issue:
        o, r = repo.split("/")
        q = f"query($o:String!,$r:String!,$n:Int!){{repository(owner:$o,name:$r){{issue(number:$n){{{_ISSUE_FIELDS}}}}}}}"
        return _issue(_gql(q, o=o, r=r, n=number)["repository"]["issue"])

    def sub_issues(self, repo: str, number: int) -> list[Issue]:
        o, r = repo.split("/")
        q = (f"query($o:String!,$r:String!,$n:Int!){{repository(owner:$o,name:$r){{issue(number:$n){{"
             f"subIssues(first:100){{nodes{{{_ISSUE_FIELDS}}}}}}}}}}}")
        return [_issue(n) for n in _gql(q, o=o, r=r, n=number)["repository"]["issue"]["subIssues"]["nodes"]]

    def resolve_project(self, ref: str) -> Project:
        if ref not in self._projects:
            org, title = ref.split("/", 1)
            q = """query($o:String!){organization(login:$o){projectsV2(first:50){nodes{id title
              field(name:"Status"){... on ProjectV2SingleSelectField{id options{id name}}}}}}}"""
            for n in _gql(q, o=org)["organization"]["projectsV2"]["nodes"]:
                p = Project(n["id"], f"{org}/{n['title']}")
                self._projects[p.ref] = p
                self._projects[f"{org}/{n['title'].lower()}"] = p
                f = n["field"]
                self._status[n["id"]] = (f["id"], {o["name"]: o["id"] for o in f["options"]})
            if ref not in self._projects and ref.lower() in self._projects:
                self._projects[ref] = self._projects[ref.lower()]
            if ref not in self._projects:
                raise KeyError(f"no project {ref}")
        return self._projects[ref]

    def add_to_project(self, project: Project, issue: Issue) -> Item:
        q = """mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}"""
        item = Item(_gql(q, p=project.id, c=issue.id)["addProjectV2ItemById"]["item"]["id"], project.id, None)
        issue.items.append(item)
        return item

    def set_status(self, item: Item, status: str) -> None:
        field_id, options = self._status[item.project_id]
        q = """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,
          itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}"""
        _gql(q, p=item.project_id, i=item.item_id, f=field_id, o=options[status])
        item.status = status

    def closing_issues(self, repo: str, pr: int) -> list[tuple[str, int]]:
        o, r = repo.split("/")
        q = """query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){
          closingIssuesReferences(first:20){nodes{number repository{nameWithOwner}}}}}}"""
        nodes = _gql(q, o=o, r=r, n=pr)["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]
        return [(n["repository"]["nameWithOwner"], n["number"]) for n in nodes]

    def open_children(self, repo: str) -> list[int]:
        o, r = repo.split("/")
        q = """query($o:String!,$r:String!){repository(owner:$o,name:$r){issues(states:OPEN,first:100){
          nodes{number parent{number}}}}}"""
        nodes = _gql(q, o=o, r=r)["repository"]["issues"]["nodes"]
        return [n["number"] for n in nodes if n["parent"]]

    def create_bug(self, repo: str, title: str, body: str) -> int:
        url = subprocess.run(["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body,
                              "--label", "bug"], check=True, capture_output=True, text=True).stdout.strip()
        number = int(url.rsplit("/", 1)[1])
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{repo}/issues/{number}", "-f", "type=Bug"],
                       check=False, capture_output=True)
        return number
