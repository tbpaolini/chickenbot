import praw
from prawcore.exceptions import Forbidden
from collections import deque
from random import shuffle
from time import sleep
from datetime import datetime, timedelta
from os import get_terminal_size

class ChickenBot():
    
    def __init__(self,
        subreddit = "all",
        question = "why did the chicken cross the road",
        wait_interval = 3600,   # Time in seconds for searching new posts
        user_cooldown = 86400,  # Time in seconds for when an user can get a new reply from the bot
        user_refresh = 1800,    # Minimum time in seconds for cleaning the replied users list
        counter_start = 0,      # The starting value of the bot replies counter
    ):
        """The bot works by searching each 1 hour (default) for the question in the title
        of posts, and then checking if the post author did not get a reply from the bot in
        the last 24 hours. If those checks have passed, the bot replies with a randonly
        selected answer.
        
        The search is made this way, instead of constantly checking for a stream of new
        submissions, because the default question do not come that often (2 to 3 times a
        day, on average). Thus continuously checking for all new posts would be a waste of
        resources (especially bandwidth)."""
        
        # Open Reddit instance
        print("Starting up ChickenBot...")
        print("Logging in Reddit... ", end="", flush=True)
        self.reddit = praw.Reddit()
        self.subreddit = self.reddit.subreddit(subreddit)
        print("Finished")

        # Question
        self.question = question.lower()
        self.query = f"(title:{self.question})"
        self.previous_post = ""     # Last post which had the question on the title
        self.wait = wait_interval   # Time to wait between checks for new posts

        # Search for the newest post with the the question
        print("Looking for the newest matching post... ", end="", flush=True)
        for submission in self.subreddit.search(self.query, sort="new"):
            
            # Get the title of the post
            title = submission.title.lower()    # Lowercase title (since substring lookup is case sensitive)
            
            # Is the question a substring of the title?
            if self.question in title:
                self.previous_post = submission.name    # Store the ID of the post
                break   # Exit the loop once the first match is found
        print("Finished")

        # Get latest users who the bot replied to
        print("Looking for the last replied users... ", end="", flush=True)
        self.replied_users = dict()                             # Dictionary of users and the time of the last bot reply
        self.user_cooldown = timedelta(seconds=user_cooldown)   # How long to wait before user can get another reply (default: 1 day)
        my_comments = self.reddit.user.me().comments.new()      # Most recent comments of the bot
        self.user_refresh = timedelta(seconds=user_refresh)     # Minimum time to refresh the replied users list
        
        for comment in my_comments:
            current_time = datetime.now()                               # Time now
            comment_time = datetime.fromtimestamp(comment.created_utc)  # Time of the bot reply
            comment_age = current_time - comment_time                   # Difference between the two times

            if comment_age < self.user_cooldown:
                # Store the user ID and comment time if the bot reply was made before the cooldown period
                replied_user = comment.submission.author.id
                self.replied_users.update({replied_user: comment_time})
        
        self.last_refresh = datetime.now()  # Store the time that the replied users list was built
        print("Finished")

        # Load blacklist of subreddits
        print("Loading subreddits blacklist... ", end="", flush=True)
        self.blacklist = set()
        try:
            with open("blacklist.txt", "r") as blacklist_file:
                for line in blacklist_file:
                    self.blacklist.add(line.strip())    # Strip the text from the line break and spaces at both ends
            print("Finished")
        except FileNotFoundError:
            print("No blacklist found")
        
        # Load responses
        print("Loading responses list... ", end="", flush=True)
        self.responses = deque()
        self.refresh_responses()
        print("Finished")

        # Update the counter for the amount replies the bot has made so far
        print("Updating bot replies counter... ", end="", flush=True)
        self.reply_counter = counter_start
        self.reply_counter_session = 0  # Replies during the current bot session
        self.log_file_name = "chickenbot_log.txt"
        try:
            with open(self.log_file_name, "r") as log_file:
                # Count the lines on the log file
                for line in log_file:
                    if line.strip():    # Do not count blank lines
                        self.reply_counter += 1
        except FileNotFoundError:
            pass
        print("Finished")

        separator = "".ljust(get_terminal_size().columns - 1, "-")
        print(f"ChickenBot has started! Bot is now running.\n{separator}")
        
    def refresh_responses(self):
        """Once all responses have been used, this method is called for
        rebuilding the responses queue"""

        # Read the responses from the file and append them to the queue
        with open("responses.txt", "r", encoding="utf-8") as responses_file:
            for line in responses_file:
                self.responses.append(line.strip())
            
            # Randomize the order of the responses
            shuffle(self.responses)
    
    def submission_testing(self, submission):
        """Checks whether a submission passes the checks for getting a reply.
        
        All checks must pass: question in the title, subreddit not on blacklist,
        author didn't get a ChickenBot's reply within the last day (default)."""

        # Is the question on the title?
        title = submission.title.lower()
        if self.question not in title:
            return False
        
        # Is the post made on a non-blacklisted subreddit?
        subreddit_id = submission.subreddit.name
        if subreddit_id in self.blacklist:
            return False
        
        # The author must not have gotten a reply from this bot recently (default: less than 24 hours ago)
        self.refresh_authors()          # Update the recently replied users list (default: less than 1 day)
        user_id = submission.author.id  # Get the ID of the current replied user
        
        if user_id in self.replied_users:   # If the user is on the recent list
            reply_time = self.replied_users[user_id]    # Last time when the user gor a reply from this bot
            reply_age = datetime.now() - reply_time     # How long has passed since then
            
            if reply_age < self.user_cooldown:          # Whether the comment age is smaller than the cooldown period
                return False
        
        # Return True when all checks passed
        return True

    def refresh_authors(self):
        """Remove from the replied authors dictionary those authors who got the last
        reply for longer than the cooldown period (default 1 day).
        
        The check is run each 30 minutes (by default)."""

        # Check if the minimum refresh period has passed
        last_refresh_age = datetime.now() - self.last_refresh
        
        # Exit the function if the minimum refresh time has not passed (default: 30 minutes)
        if last_refresh_age < self.user_refresh:
            return
        
        # Loop through the replied users dictionary
        authors_to_remove = set()
        for user_id, time in self.replied_users.items():
            
            # How long ago the user got a reply from this bot
            reply_age = datetime.now() - time
            
            # Whether that reply for longer than the cooldown period (default: 1 day)
            if reply_age >= self.user_cooldown:
                authors_to_remove.add(user_id)  # Queue to remove the user from the dictionary if the cooldown period has passed
                """NOTE
                Deleting a dictionary item during the its own iteration throws a RuntimeError.
                So instead I am storing their ids to remove from the dict after the loop.
                """
        
        # Remove the authors whose cooldown period expired
        if authors_to_remove:
            for user_id in authors_to_remove:
                del self.replied_users[user_id]
    
    def make_reply(self, submission):
        """The bot gets a response from the queue and post a reply to the post.
        
        Once all responses have been used, the queue is rebuilt. This way the
        bot only repeats the same response after all others have been used
        at least once."""

        # Whether the response queue is not empty
        if self.responses:
            # Get and remove a response from the queue
            response = self.responses.pop()
        
        else:
            # Reload the responses list when all responses have been used
            self.refresh_responses()

            # Get and remove a response from the queue
            response = self.responses.pop()
        
        # Build the reply text
        header = ">Why did the chicken cross the road?\n\n"
        footer = f"\n\n---\n\n^(This is an automatic comment made by a bot, who has answered so far to {self.reply_counter+1} doubts concerning gallinaceous roadgoing birds.)"
        reply_text = f"{header}{response}{footer}"
        
        # Posting the reply
        try:
            #print(f"{submission.title}\n{reply_text}\n----------\n")
            my_comment = submission.reply(reply_text)   # Submit the reply
            self.reply_counter += 1                     # Increase the reply counter
            self.reply_counter_session += 1

            # Add user to the replied users dictionary
            self.replied_users[submission.author.id] = datetime.now()

            # Log to file the bot comment
            with open(self.log_file_name, "a", encoding="utf-8") as log_file:
                current_time = str(datetime.now())[:19]                 # Current date and time as string (The [:19] slice strips the fractional part of the seconds)
                username = submission.author.name                       # Get the post author's username
                link = my_comment.permalink                             # Reddit link to the bot comment
                log_text = f"{current_time}\tu/{username}\t{link}\n"    # Text to be written on the log file
                log_file.write(log_text)                                # Write the log file
                print("OK:", log_text)                                  # Print the logged text to the terminal
        
        except Forbidden:   # If the bot didn't have permission to reply to the post
            
            # Log the forbiden post to file
            with open("forbiden_log.txt", "a", encoding="utf-8") as log_file:
                current_time = str(datetime.now())[:19]                 # Current date and time
                username = submission.author.name                       # Get the post author's username
                link = submission.permalink                             # Reddit link to the submission
                log_text = f"{current_time}\tu/{username}\t{link}\n"    # Text to be written on the log file
                log_file.write(log_text)                                # Write the log file
                print("FORBIDEN:", log_text)                            # Print the logged text to the terminal

    def main(self):
        """Main loop of the program."""

        while True:
            # Search for posts with the question made after the previous search
            lookup = self.subreddit.search(
                self.query,                             # Search query for the question
                sort="new",                             # Sorted by newest posts
                params={"before":self.previous_post},   # Made after the newest post found
            )

            # Loop through the found posts
            for count, submission in enumerate(lookup):
                
                # Store the ID of the newest post
                if count == 0:
                    self.previous_post = submission.name

                # Check whether the post fits the criteria for getting a reply
                if not self.submission_testing(submission):
                    continue

                # Make a reply
                self.make_reply(submission)

            # Wait for one hour (default) before searching again for posts
            sleep(self.wait)


if __name__ == "__main__":
    try:
        bot = ChickenBot()
        bot.main()
    except KeyboardInterrupt:
        print(f"\nBot stopped running. ({bot.reply_counter} replies in total, {bot.reply_counter_session} in this session)")