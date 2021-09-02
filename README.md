# Bot information

ChickenBot is a Reddit bot responds to the ever elusive question of "Why did the chicken cross the road?". It operates on the account [u/ChickenRoad_Bot](https://www.reddit.com/user/ChickenRoad_Bot), and is maintained by [u/TiagoPaolini](https://www.reddit.com/user/TiagoPaolini).

The bot works by searching once per hour for new posts containing the question on the title. On the top of that, the bot does not respond again to the same user within 24 hours. It also has a blacklist of subreddits that prefer to not get bot comments, so it will not post replies on them.

ChickenBot was made in Python 3.9.4, using the [Praw module](https://praw.readthedocs.io/en/stable/) (v7.4.0) to access the Reddit API.
