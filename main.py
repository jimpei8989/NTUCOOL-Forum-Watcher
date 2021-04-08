import logging
import json
import time
from argparse import ArgumentParser
from getpass import getpass
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(format="%(asctime)s - %(levelname)s | %(message)s", level=logging.INFO)


class Agent:
    def __init__(
        self,
        course_id: int,
        forum_ids: List[int],
        use_slack=False,
        slack_url: Optional[str] = None,
    ):
        self.sess = requests.Session()
        self.course_id = course_id
        self.forum_ids = forum_ids
        self.slack_url = slack_url if use_slack else None

    @property
    def base_url(self):
        return f"https://cool.ntu.edu.tw/courses/{self.course_id}"

    @property
    def base_api_url(self):
        return f"https://cool.ntu.edu.tw/api/v1/courses/{self.course_id}"

    def send_to_slack(self, payload):
        if self.slack_url:
            requests.post(self.slack_url, json=payload)
        else:
            logging.info("Not sending to slack")

    def login(self) -> None:
        logging.info("Trying to log in to NTU COOL ...")
        page = self.sess.get("https://cool.ntu.edu.tw/login/saml").text
        soup = BeautifulSoup(page[page.find("<form") : page.find("</form>") + 7], "html.parser")
        payload = {}
        for data in soup.find_all("input"):
            if "UsernameTextBox" in data.get("name"):
                payload[data.get("name")] = input("Username: ").strip()
            elif "PasswordTextBox" in data.get("name"):
                payload[data.get("name")] = getpass("Password: ")
            else:
                payload[data.get("name")] = data.get("value")

        url = "https://adfs.ntu.edu.tw" + soup.form.get("action")
        soup = BeautifulSoup(self.sess.post(url, data=payload).text, "html.parser")
        payload = {"SAMLResponse": soup.input.get("value")}
        url = "https://cool.ntu.edu.tw/login/saml"
        self.sess.post(url, data=payload)
        logging.info("Finished logging in.")

    def get_forum_title(self, forum_id):
        resp = self.sess.get(f"{self.base_url}/discussion_topics/{forum_id}")
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.find("h1", {"class": "discussion-title"}).text

    def get_teacher_list(self) -> List[int]:
        response = self.sess.get(f"{self.base_api_url}/users?" "per_page=50&enrollment_role_id=16")
        data = json.loads(response.text.replace("while(1);", ""))
        logging.info(f"# Teachers: {len(data)}; sample: {data[0]}")
        return [d["id"] for d in data]

    def get_ta_list(self) -> List[int]:
        response = self.sess.get(f"{self.base_api_url}/users?" "per_page=50&enrollment_role_id=17")
        data = json.loads(response.text.replace("while(1);", ""))
        logging.info(f"# TAs: {len(data)}; sample: {data[0]}")
        return [d["id"] for d in data]

    def visit_forum(self, forum_id) -> List[int]:
        forum_title = self.get_forum_title(forum_id)
        logging.info(f"Forum title: {forum_title}")
        response = self.sess.get(
            f"{self.base_api_url}/discussion_topics/{forum_id}/view"
            "?include_new_entries=1&include_enrollment_state=1&include_context_card_info=1"
        )
        data = json.loads(response.text.replace("while(1);", ""))
        threads = data["view"]

        def check(thread: dict) -> bool:
            return (
                thread.get("deleted", False)
                or thread.get("user_id", -1) in self.teaching_team
                or any(map(check, thread.get("replies", [])))
            )

        def format_thread(thread: dict) -> str:
            text = BeautifulSoup(thread.get("message", "")).get_text().replace("\n", " | ")
            return f"""- Thread ID: `{thread['id']}`
    Text: _{text[:100]}_
    Link: <{self.base_url}/discussion_topics/{forum_id}#entry-{thread['id']}>"""

        unhandled_threads = [t for t in threads if not check(t)]
        logging.info(
            f"{forum_title} - {len(unhandled_threads)} / {len(threads)} threads unhandled...\n\n"
            + "\n".join(map(format_thread, unhandled_threads))
        )
        self.send_to_slack(
            {
                "text": f"{forum_title} - {len(unhandled_threads)} / {len(threads)}"
                "threads unhandled...\n\n" + "\n".join(map(format_thread, unhandled_threads))
            }
        )

    def start(self):
        self.teaching_team = set(self.get_teacher_list() + self.get_ta_list())
        logging.info(f"# Teaching: {len(self.teaching_team)} - {self.teaching_team}")

        while True:
            self.visit_forum(self.forum_ids[0])
            time.sleep(600)


def main(args):
    with open(args.config) as f:
        config = json.load(f)
        logging.info(config)

    agent = Agent(use_slack=args.use_slack, **config)
    agent.login()
    agent.start()


def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument("--config", default="config.example.json")
    parser.add_argument("--use_slack", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_arguments())
