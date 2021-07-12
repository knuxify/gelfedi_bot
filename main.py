from datetime import datetime
from time import sleep, time
from io import BytesIO
import asyncio
import json
import os
import re

from pygelbooru import Gelbooru
from mastodon import Mastodon
from PIL import Image
import urllib

def log(content):
	"""Prints out a string prepended by the current timestamp"""
	print('\033[0;33m' + str(datetime.now()) + "\033[00m " + str(content))

logtag_post = '\033[0;34m[post]\033[00m '
logtag_action = '\033[0;32m[action]\033[00m '
logtag_info = '\033[0;36m[info]\033[00m '
logtag_error = '\033[0;31m{ERROR}\033[00m '

regexp_remove_html_tags = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')

denylist = []

with open('config.json', 'r') as fp:
	config = json.load(fp)
	fp.close()

with open('denylist.txt', 'r') as fp:
	denylist = json.load(fp)
	fp.close()

with open('posts.txt', 'r') as fp:
	posts = json.load(fp)
	fp.close()

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

post_interval = config['m_post_interval']
notification_fetch_interval = config['m_notification_fetch_interval']
visibility = config['m_visibility']

tags = config['q_tags']
exclude = config['q_exclude']
cw_tags = config['q_cw']

if not visibility in ['public', 'unlisted', 'private']:
	raise ValueError("visibility must be public, unlisted or private")

if visibility == 'public':
	log(logtag_info + "WARNING: You have set your visibility to public. This is generally NOT RECOMMENDED and oftentimes frowned upon, and on some instances bots posting on public may be a bannable offense. Use unlisted instead, unless you know what you're doing!")

async def post(visibility=visibility, reply_to_id=None, reply_to_account=None):
	if (reply_to_id and not reply_to_account) or (reply_to_account and not reply_to_id):
		raise ValueError("Make sure both reply_to_id and reply_to_account are set.")
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

		im = Image.open(path)
		im_w, im_h = im.size

		if im_w > 4096 or im_h > 4096 or os.path.getsize(path) > 8000000:
			log(logtag_post + "Image larger than max supported, resizing...")
			while im_w > 4096 or im_h > 4096:
				im_w = round(im_w / 2)
				im_h = round(im_h / 2)
				im = im.resize((im_w, im_h))
			os.remove(path)
			im.save(path, quality=100)

		im.close()

		cw = None
		for tag in cw_tags:
			if tag in g_post.tags:
				if tag == "looking_at_viewer":
					tag = "drawn eye contact / ec"
				if not cw:
					cw = "CW: " + tag
				else:
					cw = cw + ", " + tag

		try:
			media = mastodon.media_post(path, focus=(0, 1))
		except Exception as e:
			log(logtag_post + logtag_error + "Failed to upload media. Unsupported file? Retrying post.")
			log(logtag_info + "Exception:\n" + str(e))
			continue

		status_content = g_base_url + "/index.php?page=post&s=view&id=" + post_id_str + '\nsource: ' + source

		if reply_to_account:
			status_content = "@" + reply_to_account + " " + status_content

		try:
			status = mastodon.status_post(status_content, media_ids=media['id'], sensitive=True, visibility=visibility, in_reply_to_id=reply_to_id, spoiler_text=cw)
		except Exception as e:
			log(logtag_post + logtag_error + "Failed to make post. Are we being ratelimited? Is the server down? Trying again in 1 minute.")
			log(logtag_info + "Exception:\n" + str(e))
			sleep(60)
			continue

		os.remove(path)

		posts[status['id']] = post_id_str
		with open('posts.txt', 'w') as fp:
			json.dump(posts, fp)
			fp.close()

		log(logtag_post + "Finished posting: " + status['url'])

		running = False

async def notifcheck():
	global exclude
	global denylist
	notifs = mastodon.notifications()
	for n in notifs:
		if n and n['type'] == 'mention':
			status = n['status']
			if n['account']['id'] == config['m_operator_id']:
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
							fp.close()
				if "post now" in status['content']:
					log(logtag_action + "Force-posting")
					await post()
				if "deny id" in status['content']:
					new_denies = []
					for id in re.sub(regexp_remove_html_tags, '', status['content']).split():
						try:
							int(id)
						except:
							continue
						if (not id in denylist) and (not id in new_denies):
							new_denies.append(id)
					if new_denies:
						log(logtag_action + "Adding IDs to denylist: " + str(new_denies))
						denylist = denylist + new_denies
						with open('denylist.txt', 'w') as fp:
							json.dump(denylist, fp)
							fp.close()
					else:
						log(logtag_action + "Got request to add IDs to denylist, but no new denies were added.")
				if "exclude tag" in status['content']:
					new_excludes = []
					for tag in re.sub(regexp_remove_html_tags, '', status['content']).split():
						if "@" in tag or tag == "exclude" or tag == "tag":
							continue
						if (not tag in exclude) and (not tag in new_excludes):
							new_excludes.append(tag)
					if new_excludes:
						log(logtag_action + "Adding new excludes: " + str(new_excludes))
						exclude = exclude + new_excludes
						config['q_exclude'] = exclude
						with open('config.json', 'w') as fp:
							json.dump(config, fp)
							fp.close()
					else:
						log(logtag_action + "Got request to add excludes, but no new excludes were added.")
				if "cw tag" in status['content']:
					new_cw = []
					for tag in re.sub(regexp_remove_html_tags, '', status['content']).split():
						if "@" in tag or tag == "cw" or tag == "tag":
							continue
						if (not tag in cw_tags) and (not tag in new_cw):
							new_cw.append(tag)
					if new_cw:
						log(logtag_action + "Adding new CW tags: " + str(new_cw))
						cw_tags = cw_tags + new_cw
						config['q_cw'] = cw_tags
						with open('config.json', 'w') as fp:
							json.dump(config, fp)
							fp.close()
					else:
						log(logtag_action + "Got request to add tags to CW, but no new CW tags were added.")
			if "message me" in status['content']:
				log(logtag_action + "Got message request from @" + status['account']['acct'])
				await post(visibility='direct', reply_to_id=status['id'], reply_to_account=status['account']['acct'])
			log(logtag_action + "Done, clearing notifications")
			mastodon.notifications_clear()

async def invoke_forever(period, corofn, **args):
    while True:
        then = time()
        await corofn(**args)
        elapsed = time() - then
        await asyncio.sleep(period - elapsed)

if __name__ == '__main__':
	log(logtag_info + "gelfedi_bot starting up")
	botloop = asyncio.get_event_loop()
	botloop.create_task(invoke_forever(post_interval, post))
	botloop.create_task(invoke_forever(notification_fetch_interval, notifcheck))
	botloop.run_forever()
