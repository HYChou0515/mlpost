import abc
import io
import json
import os
from collections import defaultdict
from enum import Enum
from getpass import getpass
from typing import Generator, NewType, Optional, Tuple, Union

import git
import requests
import yaml
from loguru import logger
from pydantic import BaseModel

repo = git.Repo(search_parent_directories=True)
CUR_COMMIT = repo.commit("HEAD").hexsha
LAST_COMMIT = repo.commit("HEAD^").hexsha


class Presence(str, Enum):
    empty = "empty"
    draft = "draft"
    publish = "publish"


class Blog(str, Enum):
    devto = "devto"
    medium = "medium"
    hashnode = "hashnode"


class BlogStatus(BaseModel):
    post_id: Optional[str]


class PostSetting(BaseModel):
    title: str
    slug: Optional[str]
    draft: bool
    main_image: Optional[str]
    description: Optional[str]
    tags: Optional[list[str]]
    canonical_url: Optional[str]

    devto_series: Optional[str]


Post = NewType("Post", str)
ContentPath = NewType("Content", str)
SettingPath = NewType("Setting", str)
PostStatus = dict[Blog, BlogStatus]
Status = dict[Post, PostStatus]


def get_post(post_or_setting: Union[ContentPath, SettingPath]) -> Post:
    return Post(post_or_setting.rpartition(".")[0])


def get_setting(post: Post) -> SettingPath:
    return SettingPath(f"{post}.json")


def get_content(post: Post) -> ContentPath:
    return ContentPath(f"{post}.md")


class BlogApi(abc.ABC):
    blog: Blog = NotImplemented

    def read_post_content_and_setting(self, post: Post) -> Tuple[str, PostSetting]:
        with open(get_setting(post), "r", encoding="utf-8") as f:
            post_setting = PostSetting(**json.load(f))
        with open(get_content(post), "r", encoding="utf-8") as f:
            post_content = f.read()
        return post_content, post_setting

    @abc.abstractmethod
    def make_posted(self, post: Post) -> Optional[str]:
        """Make post posted

        :return post id
        """
        return NotImplemented

    @abc.abstractmethod
    def update_post(self, post: Post, post_id) -> Optional[str]:
        raise NotImplementedError


class Medium(BlogApi):
    blog: Blog = Blog.medium

    def __init__(self):
        self.author_id = (
            "1e3ed26bddc2dfac677424f1c22ef26ea0195ccf23ab80c77a310921643454c8a"
        )
        self.apikey = os.environ.get("MEDIUM_KEY", None)
        if self.apikey is None:
            self.apikey = getpass("medium key:")

    @staticmethod
    def build_payload(post_content: str, post_setting: PostSetting) -> dict:
        payload = {"content": post_content, "contentFormat": "markdown"}
        if post_setting.title is not None:
            payload["title"] = post_setting.title
        if post_setting.draft is not None:
            payload["publishStatus"] = "draft" if post_setting.draft else "public"
        if post_setting.tags is not None:
            payload["tags"] = post_setting.tags
        if post_setting.main_image is not None:
            payload["canonicalUrl"] = post_setting.canonical_url
        return payload

    def make_posted(self, post: Post) -> str:
        post_content, post_setting = self.read_post_content_and_setting(post)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.apikey}",
        }
        url = f"https://api.medium.com/v1/users/{self.author_id}/posts"
        payload = self.build_payload(post_content, post_setting)
        logger.info(f"request.post({url})")
        req = requests.post(url, headers=headers, data=json.dumps(payload))
        logger.info(f"got status_code={req.status_code}")
        if req.status_code != 201:
            raise requests.HTTPError(req)
        post_id = req.json()["data"]["id"]
        logger.info(f"got id={post_id}")
        return post_id

    def update_post(self, post: Post, post_id) -> Optional[str]:
        logger.warning("Medium does not support update post using API.")
        logger.warning(
            f"Go to `https://medium.com/p/{post_id}/settings` and delete it. "
            f"This system will create a new one. "
            f"Or you can edit it in a browser manually."
        )
        while True:
            option = input("[M]anual/[D]elete-then-create").upper()
            if option == "M":
                logger.info("Ok.")
                return
            if option == "D":
                while (
                    sure := input(
                        "Statistics of the post will be deleted. Are you sure? [y/N]"
                    ).upper()
                ) not in "YN":
                    break
                if sure == "N":
                    continue
                while input('Type "Done" after you deleted the old one.') != "Done":
                    pass
                logger.info("Ok, creating a new post")
                return self.make_posted(post)


class Devto(BlogApi):
    blog: Blog = Blog.devto

    def __init__(self):
        self.apikey = os.environ.get("DEVTO_KEY", None)
        if self.apikey is None:
            self.apikey = getpass("devto key:")

    @staticmethod
    def build_payload(post_content: str, post_setting: PostSetting) -> dict:
        payload = {"article": {"body_markdown": post_content}}
        if post_setting.title is not None:
            payload["article"]["title"] = post_setting.title
        if post_setting.draft is not None:
            payload["article"]["published"] = not post_setting.draft
        if post_setting.tags is not None:
            payload["article"]["tags"] = post_setting.tags
        if post_setting.main_image is not None:
            payload["article"]["main_image"] = post_setting.main_image
        if post_setting.canonical_url is not None:
            payload["article"]["canonical_url"] = post_setting.canonical_url
        if post_setting.description is not None:
            payload["article"]["description"] = post_setting.description
        if post_setting.devto_series is not None:
            payload["article"]["series"] = post_setting.devto_series
        return payload

    def make_posted(self, post: Post) -> str:
        post_content, post_setting = self.read_post_content_and_setting(post)
        headers = {"Content-Type": "application/json", "api-key": self.apikey}
        url = "https://dev.to/api/articles"
        payload = self.build_payload(post_content, post_setting)
        logger.info(f"request.post({url})")
        req = requests.post(url, headers=headers, data=json.dumps(payload))
        logger.info(f"got status_code={req.status_code}")
        if req.status_code != 201:
            raise requests.HTTPError(req)
        post_id = str(req.json()["id"])
        logger.info(f"got id={post_id}")
        return post_id

    def update_post(self, post: Post, post_id) -> Optional[str]:
        post_content, post_setting = self.read_post_content_and_setting(post)
        headers = {"Content-Type": "application/json", "api-key": self.apikey}
        url = f"https://dev.to/api/articles/{post_id}"
        payload = self.build_payload(post_content, post_setting)
        logger.info(f"request.put({url})")
        req = requests.put(url, headers=headers, data=json.dumps(payload))
        logger.info(f"got status_code={req.status_code}")
        if req.status_code != 200:
            raise requests.HTTPError(req)
        return post_id


class Hashnode(BlogApi):
    blog: Blog = Blog.hashnode

    def __init__(self):
        self.apikey = os.environ.get("HASHNODE_KEY", None)
        self.publication_id = "616bdc5d7c361e5132822556"
        if self.apikey is None:
            self.apikey = getpass("hashnode key:")

    def make_posted(self, post: Post) -> Optional[str]:
        post_content, post_setting = self.read_post_content_and_setting(post)

        if post_setting.draft:
            logger.warning("hashnode do not support draft in api.")
            logger.warning("Skipped.")
            return

        headers = {"Content-Type": "application/json", "Authorization": self.apikey}
        url = "https://api.hashnode.com"
        logger.info(f"request.post({url})")

        def else_none(a):
            return None if a is None else a

        query = """
            mutation createPublicationStory($input: CreateStoryInput! $publicationId: String!){
                createPublicationStory(input: $input publicationId: $publicationId){
                    post { _id }
                }
            }
        """

        body = {
            "query": query,
            "variables": {
                "input": {
                    "title": else_none(post_setting.title),
                    "slug": else_none(post_setting.slug),
                    "contentMarkdown": post_content,
                    "tags": [],  # don't know how to build tag...
                    "coverImage": else_none(post_setting.main_image),
                    "isRepublished": None
                    if post_setting.canonical_url is None
                    else {"originalArticleURL": post_setting.canonical_url},
                },
                "publicationId": self.publication_id,
            },
        }

        def drop_none(d):
            drops = []
            for k, v in d.items():
                if v is None:
                    drops.append(k)
                if isinstance(v, dict):
                    drop_none(v)
            for k in drops:
                d.pop(k)

        drop_none(body)

        req = requests.post(url, headers=headers, data=json.dumps(body))
        logger.info(f"got status_code={req.status_code}")
        if req.status_code != 200:
            raise requests.HTTPError(req)
        # req json is like
        # {'data': {'createPublicationStory': {'post': {'_id': '616beb8d7c361e513282266f'}}}}
        post_id = str(req.json()["data"]["createPublicationStory"]["post"]["_id"])
        logger.info(f"got id={post_id}")
        return post_id

    def update_post(self, post: Post, post_id) -> Optional[str]:
        post_content, post_setting = self.read_post_content_and_setting(post)

        if post_setting.draft:
            logger.warning("hashnode do not support draft in api.")
            logger.warning("Skipped.")
            return post_id

        logger.warning("Hashnode does not support update post using API.")
        logger.warning(
            f"Go to `https://hashnode.com/{self.publication_id}/dashboard/posts` and delete it. "
            f"This system will create a new one. "
            f"Or you can edit it in a browser manually."
        )
        while True:
            option = input("[M]anual/[D]elete-then-create").upper()
            if option == "M":
                logger.info("Ok.")
                return
            if option == "D":
                while (
                    sure := input(
                        "Statistics of the post will be deleted. Are you sure? [y/N]"
                    ).upper()
                ) not in "YN":
                    break
                if sure == "N":
                    continue
                while input('Type "Done" after you deleted the old one.') != "Done":
                    pass
                logger.info("Ok, creating a new post")
                return self.make_posted(post)


API_MAP: dict[Blog, BlogApi] = {
    Blog.devto: Devto(),
    Blog.medium: Medium(),
    Blog.hashnode: Hashnode(),
}


def parse_status(d: dict):
    if d is None:
        return Status()
    status: Status = {}
    for post, post_status in d.items():
        status[post] = {}
        for blog, blog_status in post_status.items():
            status[post][blog] = BlogStatus.parse_obj(blog_status)
    return Status(status)


def get_status(current=True) -> Status:
    if current:
        commit = CUR_COMMIT
    else:
        commit = LAST_COMMIT
    try:
        status_str = repo.git.show(f"{commit}:status.yml")
    except git.exc.GitCommandError:
        status_str = ""
    stream = io.StringIO(status_str)
    d = yaml.load(stream, yaml.SafeLoader)
    return parse_status(d)


def get_post_status(base: Post, current=True) -> PostStatus:
    status = get_status(current=current)
    return status.get(base, PostStatus())


def write_status(status: Status):
    with open("status.yml", "w") as f:
        s = defaultdict(dict)
        for post, post_status in status.items():
            for blog, blog_status in post_status.items():
                if isinstance(blog, Blog):
                    s[post][blog.name] = blog_status.dict()
                else:
                    s[post][blog] = blog_status.dict()
        yaml.dump(dict(s), f, default_flow_style=False)


def update_post_status(post: Post, post_status: PostStatus):
    status = get_status()
    status[post] = post_status
    write_status(status)


def all_modified_posts() -> Generator[Post, None, None]:
    yield from set(
        get_post(p)
        for p in repo.git.diff(LAST_COMMIT, CUR_COMMIT, name_only=True).split("\n")
        if p.startswith("blog-posts/") and (p.endswith(".md") or p.endswith(".json"))
    )


def commit_post(post: Post, blog_api: BlogApi):
    """
    Make current status come true.
    Make post modification come true
    Used when status entry is modified or post is modified.
    """
    post_status = get_post_status(post, current=True)
    if blog_api.blog not in post_status:
        post_status[blog_api.blog] = BlogStatus()

    blog_status = post_status[blog_api.blog]
    if blog_status.post_id is None:
        logger.info(f"post have no id, make posted...")
        blog_status.post_id = blog_api.make_posted(post)
    else:
        logger.info(f"post have id, update post...")
        blog_status.post_id = blog_api.update_post(post, blog_status.post_id)
    update_post_status(post, post_status)


def commit_all():
    """
    Check everything is commit needed
    """
    if (diff := repo.git.diff()) != "":
        logger.error(f"> git diff\n{diff}")
        assert (
            diff == ""
        ), "all tracked files should be commit before running this script"
    for post in all_modified_posts():
        if not os.path.exists(get_content(post)):
            raise FileNotFoundError(get_content(post))
        if not os.path.exists(get_setting(post)):
            raise FileNotFoundError(get_setting(post))

    for post in all_modified_posts():
        for blog_api in API_MAP.values():
            commit_post(post, blog_api)

    diff = repo.git.diff("status.yml")
    logger.info(f"> git diff status.yml\n{diff}")
    if diff != "":
        logger.info("auto-commit")
        repo.git.add("status.yml")
        repo.git.commit("-m", "auto-commit: modify status.yml")
    else:
        logger.info("nothing to do")


if __name__ == "__main__":
    commit_all()
