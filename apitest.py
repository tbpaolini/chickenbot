import praw
from prawcore.exceptions import Forbidden, NotFound
from datetime import datetime

reddit = praw.Reddit()
subreddit = reddit.subreddit("all")
question = "why did the chicken cross the road"
prev = ""

for i in range(10):
    print(i, end="\r")
    for submission in subreddit.search(question, sort="new", params={"after": prev}):
        prev=submission.name

        if question in submission.title.lower():
            with open("test.txt", "a", encoding="utf-8") as file:
                time = str(datetime.fromtimestamp(int(submission.created_utc)))
                file.write(f"{time}\t{submission.subreddit.display_name}\n")


# with open("blacklist.txt", "r") as file:
#     subs = file.readlines()
#
# with open("blacklist_id.txt", "a") as file:
#     for sub in subs:
#         line = sub.strip()
#         try:
#             file.write(reddit.subreddit(line).name + "\n")
#             print(line, "added")
#         except NotFound:
#             print(line, "not found")
#         except Forbidden:
#             print(line, "forbidden")