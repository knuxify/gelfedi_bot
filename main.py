from datetime import datetime
from time import sleep, time
from io import BytesIO
import asyncio
import json
import os

from pygelbooru import Gelbooru
from mastodon import Mastodon
import urllib

with open('config.json', 'r') as fp:
	config = json.load(fp)

with open('denylist.txt', 'r') as fp:
	denylist = json.load(fp)

with open('posts.txt', 'r') as fp:
	posts = json.load(fp)

mastodon = Mastodon(
    access_token = 'usercred.secret',
    api_base_url = config['m_base_url']
)
bot_id = mastodon.me()['id']

g_base_url = config['g_base_url']

if config['g_use_api_key']:
	gelbooru = Gelbooru(config['g_api_key'], config['g_api_user_id'])
else:
	gelbooru = Gelbooru()

tags = config['q_tags']
exclude = config['q_exclude']
post_interval = config['m_post_interval']
notification_fetch_interval = config['m_notification_fetch_interval']

def log(content):
	"""Prints out a string prepended by the current timestamp"""
	print('\033[0;33m' + str(datetime.now()) + "\033[00m " + str(content))

logtag_post = '\033[0;34m[post]\033[00m '
logtag_action = '\033[0;31m[action]\033[00m '
logtag_info = '\033[0;36m[info]\033[00m '

async def post():
	running = True
	while running:
		log(logtag_post + "Getting random image...")
		g_post = await gelbooru.random_post(tags=tags, exclude_tags=exclude)

		if g_post.id in denylist:
			log(logtag_post + "...got post on denylist, let's try again.")
			continue

		post_id_str = str(g_post.id)

		log(logtag_post + "Got image with ID " + post_id_str)

		url = g_post.file_url
		path = os.path.join(os.getcwd(), g_post.filename)
		urllib.request.urlretrieve(url, path)

		if g_post.source:
			source = g_post.source
		else:
			source = 'unknown'

		media = mastodon.media_post(path)

		status_content = g_base_url + "/index.php?page=post&s=view&id=" + post_id_str + '\nsource: ' + source

		status = mastodon.status_post(status_content, media_ids=media['id'], sensitive=True, visibility='unlisted')

		os.remove(path)

		posts[status['id']] = post_id_str
		with open('posts.txt', 'w') as fp:
			json.dump(posts, fp)

		log(logtag_post + "Finished posting: " + status['url'])

		running = False

async def notifcheck():
	notifs = mastodon.notifications(account_id=config['m_operator_id'])
	for n in notifs:
		if n and n['type'] == 'mention' and n['account']['id'] == config['m_operator_id']:
			status = n['status']
			if "in_reply_to_id" in status and status['in_reply_to_id']:
				target_status_id = status['in_reply_to_id']
				if "delete this" in status['content'] and status['in_reply_to_account_id'] == bot_id:
					log(logtag_action + "Deleting post: " + status['url'])
					try:
						denylist.append(posts[target_status_id])
					except KeyError:
						log(logtag_action + "WARNING: Couldn't find ID of post in posts dict, cannot add to denylist!")
					mastodon.status_delete(target_status_id)
					with open('denylist.txt', 'w') as fp:
						json.dump(denylist, fp)
			if "post now" in status['content']:
				log(logtag_action + "Force-posting")
				await post()
			log(logtag_action + "Done, clearing notifications.")
			mastodon.notifications_clear()

async def invoke_forever(period, corofn):
    while True:
        then = time()
        await corofn()
        elapsed = time() - then
        await asyncio.sleep(period - elapsed)

if __name__ == '__main__':
	log(logtag_info + "gelfedi_bot starting up")
	botloop = asyncio.get_event_loop()
	botloop.create_task(invoke_forever(post_interval, post))
	botloop.create_task(invoke_forever(notification_fetch_interval, notifcheck))
	botloop.run_forever()
