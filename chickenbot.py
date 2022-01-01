import praw
import pickle
import re
from prawcore.exceptions import Forbidden, PrawcoreException
from praw.exceptions import ClientException
from traceback import format_exc
from collections import deque
from random import shuffle
from time import sleep
from datetime import datetime, timedelta
from os import get_terminal_size
from pathlib import Path
from threading import Thread
from signal import signal, SIGINT
from urllib.parse import quote

class ChickenBot():
    
    def __init__(self,
        subreddit = "all",
        question = "why did the chicken cross the road",
        wait_interval = 3600,   # Time in seconds for searching new posts
        user_cooldown = 86400,  # Time in seconds for when an user can get a new reply from the bot
        user_refresh = 1800,    # Minimum time in seconds for cleaning the replied users list
        message_wait = 900,     # Minimum time in seconds for checking new private messages
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
        self.previous_reply_time = datetime.utcnow()    # Time of the latest bot reply
        self.wait = wait_interval   # Time to wait between checks for new posts

        # Get latest users who the bot replied to
        print("Looking for the latest replied users... ", end="", flush=True)
        self.replied_users = dict()                             # Dictionary of users and the time of the last bot reply
        self.user_cooldown = timedelta(seconds=user_cooldown)   # How long to wait before user can get another reply (default: 1 day)
        my_comments = self.reddit.user.me().comments.new()      # Most recent comments of the bot
        self.user_refresh = timedelta(seconds=user_refresh)     # Minimum time to refresh the replied users list
        
        for count, comment in enumerate(my_comments):
            current_time = datetime.utcnow()                               # Time now
            comment_time = datetime.fromtimestamp(comment.created_utc)  # Time of the bot reply
            comment_age = current_time - comment_time                   # Difference between the two times
            if count == 0:
                self.previous_post = comment.submission.name            # Latest submission replied by bot
                self.previous_reply_time = datetime.fromtimestamp(      # Time of the latest bot reply
                    comment.created_utc
                )

            if comment_age < self.user_cooldown:
                # Store the user ID and comment time if the bot reply was made before the cooldown period
                replied_user = comment.submission.author.id
                self.replied_users.update({replied_user: comment_time})
        
        self.last_refresh = datetime.utcnow()  # Store the time that the replied users list was built
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
        self.temp_file = Path("temp.bin")   # Temporary file for the responses in the queue
        
        if self.temp_file.exists():
            # Load the responses from the temporary file, if one exists
            with open(self.temp_file, "rb") as temp:
                self.responses = pickle.load(temp)
        else:
            # If not, then build the response queue from scratch
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

        # Interval to check for private messages
        self.message_wait = message_wait

        self.running = True     # Indicate to the threads that the bot is running
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
        
        # Create the temporary file for the responses queue
        self.save_temp()
    
    def save_temp(self):
        """Saves a temporary file for the responses queue.
        This allows the bot, when restarted, to continue from where it stopped."""
        
        # Create the temporary file with the responses queue
        with open(self.temp_file, "wb") as temp:
            pickle.dump(self.responses, temp)
    
    def submission_testing(self, submission):
        """Checks whether a submission passes the checks for getting a reply.
        
        All checks must pass: post made after bot's previous reply, question in
        the title, subreddit not on blacklist, author didn't get a ChickenBot's
        reply within the last day (default)."""

        # Was the submission made after the last bot reply?
        post_time = datetime.fromtimestamp(submission.created_utc)
        if post_time < self.previous_reply_time:
            return False

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
            reply_age = datetime.utcnow() - reply_time     # How long has passed since then
            
            if reply_age < self.user_cooldown:          # Whether the comment age is smaller than the cooldown period
                return False
        
        # Return True when all checks passed
        return True

    def refresh_authors(self):
        """Remove from the replied authors dictionary those authors who got the last
        reply for longer than the cooldown period (default 1 day).
        
        The check is run each 30 minutes (by default)."""

        # Check if the minimum refresh period has passed
        last_refresh_age = datetime.utcnow() - self.last_refresh
        
        # Exit the function if the minimum refresh time has not passed (default: 30 minutes)
        if last_refresh_age < self.user_refresh:
            return
        
        # Loop through the replied users dictionary
        authors_to_remove = set()
        for user_id, time in self.replied_users.items():
            
            # How long ago the user got a reply from this bot
            reply_age = datetime.utcnow() - time
            
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

        # Whether the response queue is empty
        if not self.responses:
            # Reload the responses list when all responses have been used
            self.refresh_responses()

        # Get and remove a response from the queue
        response = self.responses.pop().replace("&NewLine;", "\n\n")
        self.save_temp()
        
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
            self.has_replied = True     # Flag that the bot has replied on the current cycle

            # Add user to the replied users dictionary
            self.replied_users[submission.author.id] = datetime.utcnow()

            # Log to file the bot comment
            with open(self.log_file_name, "a", encoding="utf-8") as log_file:
                current_time = str(datetime.utcnow())[:19]              # Current date and time as string (The [:19] slice strips the fractional part of the seconds)
                username = submission.author.name                       # Get the post author's username
                link = my_comment.permalink                             # Reddit link to the bot comment
                log_text = f"{current_time}\tu/{username}\t{link}\n"    # Text to be written on the log file
                log_file.write(log_text)                                # Write the log file
                print("OK:", log_text, end="")                          # Print the logged text to the terminal
            
            # Generate link so the original poster can delete the comment
            # (the 'urllib.parse.quote()' function escapes special characters and spaces)
            message_subject = quote("Removal of ChickenBot's comment", safe="")
            message_body = quote(f"Please remove {link}\n\n[do not edit the first line]", safe="")
            removal_link = f"/message/compose/?to=u%2FChickenRoad_Bot&subject={message_subject}&message={message_body}"
            
            # Edit the comment to append the removal link
            edited_comment = my_comment.body + f" ^(If you are the thread's author, you can) [^(click here)]({removal_link}) ^(to delete this comment \(takes up to 15 minutes\).)"
            my_comment.edit(edited_comment)
        
        except Forbidden as error:   # If the bot didn't have permission to reply to the post
            
            # Log the forbiden post to file
            with open("forbiden_log.txt", "a", encoding="utf-8") as log_file:
                current_time = str(datetime.utcnow())[:19]              # Current date and time
                username = submission.author.name                       # Get the post author's username
                link = submission.permalink                             # Reddit link to the submission
                log_text = f"{current_time}\tu/{username}\t{link}\t{error}\n"    # Text to be written on the log file
                log_file.write(log_text)                                # Write the log file
                print("FORBIDEN:", log_text, end="")                    # Print the logged text to the terminal
        
        except PrawcoreException as error:   # If some other problem happened
            current_time = str(datetime.utcnow())[:19]
            log_text = f"{current_time}\tu/{username}\t{link}\t{error}\n"
            print("Failed:", log_text, end="")

            with open("forbiden_log.txt", "a", encoding="utf-8") as log_file:
                log_file.write(log_text)

            my_exception = format_exc()
            my_date = current_time + "\n\n"
            with open("error_log.txt", "a", encoding="utf-8") as error_log:
                error_log.write(my_date)
                error_log.write(my_exception)
                error_log.write("\n\n---------------\n")

    def check_submissions(self):
        """Look for submissions for replying to."""

        while self.running:
            # Track whether the bot has replied this cycle
            self.has_replied = False

            # Search for posts with the question made after the previous search
            lookup = self.subreddit.search(
                self.query,                             # Search query for the question
                sort="new",                             # Sorted by newest posts
                # params={"before":self.previous_post},   # Made after the newest post found
            )

            # Loop through the found posts
            try:
                for count, submission in enumerate(lookup):
                    
                    # Store the ID of the newest post
                    if count == 0:
                        self.previous_post = submission.name

                    # Check whether the post fits the criteria for getting a reply
                    if not self.submission_testing(submission):
                        continue

                    # Make a reply
                    self.make_reply(submission)
            
            # Connection to the Reddit server failed
            except PrawcoreException as error:
                current_time = str(datetime.utcnow())[:19]
                print("Warning:", current_time, error)
                my_exception = format_exc()
                my_date = str(datetime.now())[:19] + "\n\n"

                with open("error_log.txt", "a", encoding="utf-8") as error_log:
                    error_log.write(my_date)
                    error_log.write(my_exception)
                    error_log.write("\n\n---------------\n")

            # Update the last reply time if the bot has replied this cycle
            if self.has_replied:
                self.previous_reply_time = datetime.utcnow()
            
            # Wait for one hour (default) before searching again for posts
            sleep(self.wait)
    
    def private_messages(self):
        """Listens to the bot account's private chat, in order to process removal requests."""

        # Regular expression to extract the comment ID from the message body
        message_regex = re.compile(r"remove /r/.+?/comments/.+?/.+?/(\w+)")

        # Bot's user ID
        my_id = self.reddit.user.me().fullname
        
        # Check for new private messages
        while self.running:
            try:
                private_inbox = self.reddit.inbox.messages()
                for message in private_inbox:

                    # Skip the message if it has already been read
                    if not message.new: continue

                    # Mark the message as "read"
                    message.mark_read()
                    
                    # Get the author and the requested comment
                    message_author_id = message.author_fullname
                    message_author = self.reddit.redditor(fullname=message_author_id)
                    if message_author is None: continue
                    
                    # Get the comment ID from the message
                    search = message_regex.search(message.body)
                    if search is None: continue
                    comment_id = search.group(1)
                    
                    try:
                        # Get the paramentes of the comment's thread
                        comment = self.reddit.comment(comment_id)
                        post_id = comment.link_id.split("_")[1]
                        post = self.reddit.submission(post_id)
                        post_title = post.title
                        post_url = post.permalink
                        post_author_id = post.author_fullname
                    
                    except (ClientException, AttributeError):
                        # If the comment was not found
                        if "remov" in message.subject:
                            message_author.message(
                                subject = "ChickenBot comment removal",
                                message = f"Sorry, the requested comment '{comment_id}' could not be found. Possibly it was already deleted."
                            )
                        continue
                    
                    # Permanent link to the comment
                    comment_url = comment.permalink

                    # Verify the author and respond
                    
                    if post_author_id == message_author_id:
                        # Delete comment if it was requested by the own author

                        # Check if the bot is the comment's author
                        if comment.author_fullname == my_id:
                            comment.delete()
                            message_author.message(
                                subject = "ChickenBot comment removed",
                                message = f"The bot has deleted [its comment]({comment_url}) from your post [{post_title}]({post_url}).\n\nSorry for any inconvenience that the bot might have caused."
                            )
                            
                            # The bot won't post to this author's threads for the duration of their cooldown time
                            self.replied_users[post.author.id] = datetime.utcnow()
                        
                        else:
                            message_author.message(
                                subject = "ChickenBot comment removal",
                                message = "Sorry, the bot can only delete comments made by itself."
                            )

                    else:
                        # Refuse to delete if it was someone else who requested
                        message_author.message(
                            subject = "ChickenBot comment",
                            message = f"Sorry, only the original poster u/{post.author.name} can request the removal of [my comment]({comment_url}) on the thread [{post_title}]({post_url})."
                        )
            
            # Logs the error if something wrong happens while handling messages
            # (probably Reddit was down or the user blocked the bot)
            except PrawcoreException as error:
                current_time = str(datetime.utcnow())[:19]
                print("Warning:", current_time, error)
                my_exception = format_exc()
                my_date = str(datetime.now())[:19] + "\n\n"

                with open("error_log.txt", "a", encoding="utf-8") as error_log:
                    error_log.write(my_date)
                    error_log.write(my_exception)
                    error_log.write("\n\n---------------\n")
            
            # Wait for some time before checking for new private messages
            sleep(self.message_wait)
    
    def main(self):
        """Main loop of the program"""
        
        # Create threads for the listeners
        submissions_listener = Thread(target=self.check_submissions)
        messages_listener = Thread(target=self.private_messages)
        
        # Set the threads to 'daemoninc'
        # (daemon threads do not prevent their parent program from exiting)
        submissions_listener.daemon = True
        messages_listener.daemon = True

        # Begin the child threads
        submissions_listener.start()
        messages_listener.start()

        # Catch a keyboard interrupt, so the threads can terminate and the program exit
        signal(SIGINT, self.clean_exit)
        while True:
            submissions_listener.join(1)
            messages_listener.join(1)
        """NOTE
        In Python, there isn't any actual 'clean' way to terminate a thread.
        By default, a KeyboardInterrupt is caught by an arbitrary thread,
        while others remain running.

        Using the signal() function forces the main thread to catch the interrupt.
        Then the bot set the 'self.running' flag to False, which makes the its child
        threads to exit their loop.

        Finally, the whole program exits.
        """
    
    def clean_exit(self, *args):
        """Close the program."""

        self.running = False
        raise SystemExit


if __name__ == "__main__":
    try:
        bot = ChickenBot()
        bot.main()
    except (SystemExit, KeyboardInterrupt):
        print(f"\nBot stopped running. ({bot.reply_counter} replies in total, {bot.reply_counter_session} in this session)")
