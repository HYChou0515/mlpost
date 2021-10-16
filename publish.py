import abc
import io
import json
import os
from collections import defaultdict
from enum import Enum
from getpass import getpass
from typing import Generator, NewType, Optional

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


Post = NewType("Post", str)
PostStatus = dict[Blog, BlogStatus]
Status = dict[Post, PostStatus]


class BlogApi(abc.ABC):
    blog: Blog = NotImplemented

    @abc.abstractmethod
    def is_published(self, post_id) -> bool:
        return NotImplemented

    @abc.abstractmethod
    def make_posted(self, post: Post) -> int:
        """Make post posted

        :return post id
        """
        return NotImplemented

    @abc.abstractmethod
    def update_post(self, post: Post, post_id) -> None:
        raise NotImplementedError


class Devto(BlogApi):
    blog: Blog = Blog.devto

    def __init__(self):
        self.apikey = os.environ.get("DEVTO_KEY", None)
        if self.apikey is None:
            self.apikey = getpass("devto key:")

    def is_published(self, post_id) -> bool:
        headers = {"Accept": "application/json", "api-key": self.apikey}
        url = f"https://dev.to/api/articles/{post_id}"
        logger.info(f"request.get({url})...")
        req = requests.get(url, headers=headers)
        logger.info(f"got status_code={req.status_code}")
        if req.status_code == 200:
            return True
        if req.status_code == 404:
            return False
        raise requests.HTTPError(req)

    def make_posted(self, post: Post) -> int:
        with open(post, "r", encoding="utf-8") as f:
            post_str = f.read()
        headers = {"Content-Type": "application/json", "api-key": self.apikey}
        url = "https://dev.to/api/articles"
        payload = {"article": {"body_markdown": post_str}}
        logger.info(f"request.post({url})")
        req = requests.post(url, headers=headers, data=json.dumps(payload))
        logger.info(f"got status_code={req.status_code}")
        if req.status_code != 201:
            raise requests.HTTPError(req)
        logger.info(f'got id={req.json()["id"]}')
        return req.json()["id"]

    def update_post(self, post: Post, post_id) -> None:
        with open(post, "r", encoding="utf-8") as f:
            post_str = f.read()
        headers = {"Content-Type": "application/json", "api-key": self.apikey}
        url = f"https://dev.to/api/articles/{post_id}"
        payload = {"article": {"body_markdown": post_str}}
        logger.info(f"request.put({url})")
        req = requests.put(url, headers=headers, data=json.dumps(payload))
        logger.info(f"got status_code={req.status_code}")
        if req.status_code != 200:
            raise requests.HTTPError(req)


API_MAP: dict[Blog, BlogApi] = {
    Blog.devto: Devto(),
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


def get_post_status(post: Post, current=True) -> PostStatus:
    status = get_status(current=current)
    return status.get(post, PostStatus())


def write_status(status: Status):
    with open("status.yml", "w") as f:
        s = defaultdict(dict)
        for post, post_status in status.items():
            for blog, blog_status in post_status.items():
                s[post][blog.name] = blog_status.dict()
        yaml.dump(dict(s), f, default_flow_style=False)


def update_post_status(post: Post, post_status: PostStatus):
    status = get_status()
    status[post] = post_status
    write_status(status)


def all_modified_posts() -> Generator[Post, None, None]:
    yield from (
        p
        for p in repo.git.diff(LAST_COMMIT, CUR_COMMIT, name_only=True).split("\n")
        if p.startswith("blog-posts/") and p.endswith(".md")
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
        logger.info(f'post have no id, make posted...')
        blog_status.post_id = str(blog_api.make_posted(post))
        update_post_status(post, post_status)
    else:
        logger.info(f'post have id, update post...')
        blog_api.update_post(post, blog_status.post_id)


def is_published(post_id, blog: Blog) -> bool:
    blog_api = API_MAP[blog]
    return blog_api.is_published(post_id)


def commit_all():
    """
    Check everything is commit needed
    """
    if (diff := repo.git.diff()) != '':
        logger.error(f'> git diff\n{diff}')
        assert diff == '', 'all tracked files should be commit before running this script'
    for post in all_modified_posts():
        if not os.path.exists(post):
            raise FileNotFoundError(post)

    for post in all_modified_posts():
        for blog_api in API_MAP.values():
            commit_post(post, blog_api)

    diff = repo.git.diff('status.yml')
    logger.info(f'> git diff status.yml\n{diff}')
    if diff != '':
        logger.info('auto-commit')
        repo.git.add('status.yml')
        repo.git.commit('-m', 'auto-commit: modify status.yml')
    else:
        logger.info('nothing to do')


if __name__ == '__main__':
    commit_all()
