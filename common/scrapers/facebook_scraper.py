import json
import datetime
import csv
import time
import re
try:
    from urllib.request import urlopen, Request
except ImportError:
    from urllib2 import urlopen, Request

import common
from common.posts.facebook_post import FacebookPost as FacebookPost

#TODO: Object model is a little janky here

class FacebookScraper(object):
    def __init__(self, criteria):
        self.scrape_data = list()
        self.criteria = criteria

    def scrape(self):
        """
        Scrape the group we're interested in with supplied criteria
        """
        self.scrape_data = scrape_group(
            self.criteria["group_id"],
            self.criteria["app_id"] + "|" + self.criteria["app_secret"],
            self.criteria["date_range"][0],
            self.criteria["date_range"][1])

    def dump_scraped_posts(self, filename):
        """
        Dumps posts from previous scraping to a csv file

        :param filename: File to dump our scrapejob
        """
        with open(filename.format(self.criteria['group_id']), 'w') as file:
            w = csv.writer(file)
            w.writerow(["status_id", "status_message", "status_author", "link_name",
                    "status_type", "status_link", "status_published",
                    "num_reactions", "num_comments", "num_shares", "num_likes",
                    "num_loves", "num_wows", "num_hahas", "num_sads", "num_angrys",
                    "num_special"])

            for post in self.scrape_data:
                w.writerow(post.get_tuple())

    def get_group_friendly_name(self):
        return get_group_friendly_name(
            self.criteria["group_id"],
            self.criteria["app_id"] + "|" + self.criteria["app_secret"])

#TODO: Add a wat to get fb froup friendly name

###############################################################
def request_until_succeed(url):
    req = Request(url)
    success = False
    data = None
    retry_count = 15

    while success is False:

        try:
            response = urlopen(req)
            if response.getcode() == 200:
                data = response.read().decode('utf-8')
                success = True

        except Exception as e:

            if retry_count <= 0:
                raise e

            print(e)
            time.sleep(5)

            print("Error for URL {}: {}".format(url, datetime.datetime.now()))
            print("Retrying.")
            retry_count -= 1

    return data

def unicode_decode(text):
    try:
        return text.encode('utf-8').decode()
    except UnicodeDecodeError:
        return text.encode('utf-8')

def getFacebookPageFeedUrl(base_url):

    # Construct the URL string; see http://stackoverflow.com/a/37239851 for
    # Reactions parameters
    fields = "&fields=message,link,created_time,type,name,id," + \
        "comments.limit(0).summary(true),shares,reactions" + \
        ".limit(0).summary(true),from"
    url = base_url + fields

    return url

def getReactionsForStatuses(base_url):

    reaction_types = ['like', 'love', 'wow', 'haha', 'sad', 'angry']
    reactions_dict = {}   # dict of {status_id: tuple<6>}

    for reaction_type in reaction_types:
        fields = "&fields=reactions.type({}).limit(0).summary(total_count)".format(
            reaction_type.upper())

        url = base_url + fields

        data = json.loads(request_until_succeed(url))['data']

        data_processed = set()  # set() removes rare duplicates in statuses
        for status in data:
            id = status['id']
            count = status['reactions']['summary']['total_count']
            data_processed.add((id, count))

        for id, count in data_processed:
            if id in reactions_dict:
                reactions_dict[id] = reactions_dict[id] + (count,)
            else:
                reactions_dict[id] = (count,)

    return reactions_dict


def processFacebookPageFeedStatus(status):

    # The status is now a Python dictionary, so for top-level items,
    # we can simply call the key.

    # Additionally, some items may not always exist,
    # so must check for existence first

    status_id = status['id']
    status_type = status['type']

    status_message = '' if 'message' not in status else \
        unicode_decode(status['message'])
    link_name = '' if 'name' not in status else \
        unicode_decode(status['name'])
    status_link = '' if 'link' not in status else \
        unicode_decode(status['link'])

    # Time needs special care since a) it's in UTC and
    # b) it's not easy to use in statistical programs.

    status_published = datetime.datetime.strptime(
        status['created_time'], '%Y-%m-%dT%H:%M:%S+0000')
    status_published = status_published + \
        datetime.timedelta(hours=-5)  # EST
    status_published = status_published.strftime(
        '%Y-%m-%d %H:%M:%S')  # best time format for spreadsheet programs
    status_author = unicode_decode(status['from']['name'])

    # Nested items require chaining dictionary keys.

    num_reactions = 0 if 'reactions' not in status else \
        status['reactions']['summary']['total_count']
    num_comments = 0 if 'comments' not in status else \
        status['comments']['summary']['total_count']
    num_shares = 0 if 'shares' not in status else status['shares']['count']

    return (status_id, status_message, status_author, link_name, status_type,
            status_link, status_published, num_reactions, num_comments, num_shares)


def scrape_group(group_id, access_token, since_date, until_date):

    fb_post_data = []
    has_next_page = True
    num_processed = 0   # keep a count on how many we've processed
    scrape_starttime = datetime.datetime.now()

    # /feed endpoint pagenates througn an `until` and `paging` parameters
    until = ''
    paging = ''
    base = "https://graph.facebook.com/v2.10"
    node = "/{}/feed".format(group_id)
    parameters = "/?limit={}&access_token={}".format(100, access_token)
    since = "&since={}".format(since_date) if since_date \
        is not '' else ''
    until = "&until={}".format(until_date) if until_date \
        is not '' else ''

    print("Scraping {} Facebook Group: {}\n".format(
        group_id, scrape_starttime))

    while has_next_page:
        until = '' if until is '' else "&until={}".format(until)
        paging = '' if until is '' else "&__paging_token={}".format(paging)
        base_url = base + node + parameters + since + until + paging

        url = getFacebookPageFeedUrl(base_url)

        statuses = json.loads(request_until_succeed(url))
        reactions = getReactionsForStatuses(base_url)

        for status in statuses['data']:

            # Ensure it is a status with the expected metadata
            if 'reactions' in status:
                status_data = processFacebookPageFeedStatus(status)
                reactions_data = reactions[status_data[0]]

                # calculate thankful/pride through algebra
                num_special = status_data[7] - sum(reactions_data)
                post_data = FacebookPost(status_data + reactions_data + (num_special,))
                fb_post_data.append(post_data)

            # output progress occasionally to make sure code is not
            # stalling
            num_processed += 1
            if num_processed % 100 == 0:
                print("{} Statuses Processed: {}".format
                      (num_processed, datetime.datetime.now()))

        # if there is no next page, we're done.
        if 'paging' in statuses:
            next_url = statuses['paging']['next']
            until = re.search('until=([0-9]*?)(&|$)', next_url).group(1)
            paging = re.search(
                '__paging_token=(.*?)(&|$)', next_url).group(1)

        else:
            has_next_page = False

    print("\nDone!\n{} Statuses Processed in {}".format(
          num_processed, datetime.datetime.now() - scrape_starttime))

    return fb_post_data

def get_group_friendly_name(group_id, access_token):
    base = "https://graph.facebook.com/v2.10"
    node = "/{}".format(group_id)
    params = "/?access_token={}".format(access_token)

    base_url = base+node+params

    group = json.loads(request_until_succeed(base_url))

    return group['name']
