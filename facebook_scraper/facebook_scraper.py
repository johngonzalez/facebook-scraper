import itertools
import json
import re
import warnings
from datetime import datetime

from requests_html import HTML, HTMLSession

from . import utils


_likes_regex = re.compile(r'like_def[^>]*>([0-9,.]+)')
_comments_regex = re.compile(r'cmt_def[^>]*>([0-9,.]+)')
_shares_regex = re.compile(r'([0-9,.]+)\s+Shares', re.IGNORECASE)
_link_regex = re.compile(r"href=\"https:\/\/lm\.facebook\.com\/l\.php\?u=(.+?)\&amp;h=")

_cursor_regex = re.compile(r'href:"(/page_content[^"]+)"')  # First request
_cursor_regex_2 = re.compile(r'href":"(\\/page_content[^"]+)"')  # Other requests
_cursor_regex_3 = re.compile(r'\shref="(\/groups\/[^"]+bac=[^"]+)"')  # for Group requests

_photo_link = re.compile(r"href=\"(/[^\"]+/photos/[^\"]+?)\"")
_image_regex = re.compile(
    r"<a href=\"([^\"]+?)\" target=\"_blank\" class=\"sec\">View Full Size<\/a>", re.IGNORECASE
)
_image_regex_lq = re.compile(r"background-image: url\('(.+)'\)")
_post_url_regex = re.compile(r'/story.php\?story_fbid=')

_more_url_regex = re.compile(r'(?<=…\s)<a href="([^"]+)')
_post_story_regex = re.compile(r'href="(\/story[^"]+)" aria')

_shares_and_reactions_regex = re.compile(
    r'<script>.*bigPipe.onPageletArrive\((?P<data>\{.*RelayPrefetchedStreamCache.*\})\);.*</script>'
)
_bad_json_key_regex = re.compile(r'(?P<prefix>[{,])(?P<key>\w+):')


class FacebookScraper:
    base_url = 'https://m.facebook.com/'
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/76.0.3809.87 Safari/537.36"
    )
    cookie = 'locale=en_US;'
    default_headers = {
        'User-Agent': user_agent,
        'Accept-Language': 'en-US,en;q=0.5',
        'cookie': cookie,
    }

    def __init__(self, session=None, requests_kwargs=None):
        if session is None:
            session = HTMLSession()
            session.headers.update(self.default_headers)

        if requests_kwargs is None:
            requests_kwargs = {}

        self.session = session
        self.requests_kwargs = requests_kwargs

    def get_pages(self, url):
        response = self.get(url)

        html = HTML(html=response.text.replace('<!--', '').replace('-->', ''))
        cursor_blob = html.html
        next_page_url = self.find_cursor(cursor_blob)

        yield html

        while next_page_url is not None:
            url = utils.urljoin(self.base_url, next_page_url)
            response = self.get(url)
            data = json.loads(response.text.replace('for (;;);', '', 1))

            html = None
            cursor_blob = None
            next_page_url = None

            for action in data['payload']['actions']:
                if action['cmd'] == 'replace':
                    html = HTML(html=action['html'], url=self.base_url)
                elif action['cmd'] == 'script':
                    cursor_blob = action['code']

            if html is not None:
                yield html

            if cursor_blob is not None:
                next_page_url = self.find_cursor(html.html)

    def get_posts(self, account, pages=10, extra_info=False):
        url = utils.urljoin(self.base_url, f'/{account}/posts/')

        for i, page in enumerate(self.get_pages(url)):
            yield from self.extract_posts(page, extra_info=extra_info)

            if i >= pages - 1:
                break

    def get_group_posts(self, group, pages=10, extra_info=False):
        url = utils.urljoin(self.base_url, f'/groups/{group}/')

        while True:
            response = self.session.get(url)
            response.raise_for_status()
            html = HTML(html=response.html.html.replace('<!--', '').replace('-->', ''))
            cursor_blob = html.html

            for article in html.find('article'):
                post = self.extract_single_post(article)
                if extra_info:
                    post = self.fetch_share_and_reactions(post)
                yield post

            pages -= 1
            if pages <= 0:
                return

            cursor = self.find_cursor(cursor_blob)

            if cursor is not None:
                url = utils.urljoin(self.base_url, cursor)

    def find_cursor(self, text):
        match = _cursor_regex.search(text)
        if match:
            return match.groups()[0]

        match = _cursor_regex_2.search(text)
        if match:
            value = match.groups()[0]
            return value.encode('utf-8').decode('unicode_escape').replace('\\/', '/')

        match = _cursor_regex_3.search(text)
        if match:
            value = match.groups()[0]
            return value.encode('utf-8').decode('unicode_escape').replace('\\/', '/')

        return None

    def get(self, url, **kwargs):
        return self.session.get(url=url, **self.requests_kwargs, **kwargs)

    def extract_posts(self, node, extra_info=False):
        for article in node.find('article'):
            post = self.extract_single_post(article)
            if extra_info:
                post = self.fetch_share_and_reactions(post)
            yield post

    def extract_single_post(self, node):
        text, post_text, shared_text = self.extract_text(node)

        return {
            'post_id': self.extract_post_id(node),
            'text': text,
            'post_text': post_text,
            'shared_text': shared_text,
            'time': self.extract_time(node),
            'image': self.extract_image(node),
            'likes': utils.find_and_search(node, 'footer', _likes_regex, utils.parse_int) or 0,
            'comments': utils.find_and_search(node, 'footer', _comments_regex, utils.parse_int)
            or 0,
            'shares': utils.find_and_search(node, 'footer', _shares_regex, utils.parse_int) or 0,
            'post_url': self.extract_post_url(node),
            'link': self.extract_link(node),
        }

    def extract_post_id(self, article):
        try:
            data_ft = json.loads(article.attrs['data-ft'])
            return data_ft['mf_story_key']
        except (KeyError, ValueError):
            warnings.warn("Could not extract post id")
            return None

    def extract_text(self, article):
        # Open this article individually because not all content is fully loaded when skimming through pages
        # This ensures the full content can be read
        hasMore = _more_url_regex.search(article.html)
        if hasMore:
            match = _post_story_regex.search(article.html)
            if match:
                url = utils.urljoin(self.base_url, match.groups()[0].replace("&amp;", "&"))
                response = self.get(url)
                article = response.html.find('.story_body_container', first=True)

        nodes = article.find('p, header')
        if nodes:
            post_text = []
            shared_text = []
            ended = False
            for node in nodes[1:]:
                if node.tag == "header":
                    ended = True

                # Remove '... More'
                # This button is meant to display the hidden text that is already loaded
                # Not to be confused with the 'More' that opens the article in a new page
                if node.tag == "p":
                    node = HTML(html=node.html.replace('>… <', '><', 1).replace('>More<', '', 1))

                if not ended:
                    post_text.append(node.text)
                else:
                    shared_text.append(node.text)

            text = '\n'.join(itertools.chain(post_text, shared_text))
            post_text = '\n'.join(post_text)
            shared_text = '\n'.join(shared_text)

            return text, post_text, shared_text

        return None

    def extract_time(self, article):
        try:
            data_ft = json.loads(article.attrs['data-ft'])
            page_insights = data_ft['page_insights']
        except (KeyError, ValueError):
            return None

        for page in page_insights.values():
            try:
                timestamp = page['post_context']['publish_time']
                return datetime.fromtimestamp(timestamp)
            except (KeyError, ValueError):
                continue
        return None

    def extract_photo_link(self, article):
        match = _photo_link.search(article.html)
        if not match:
            return None

        url = utils.urljoin(self.base_url, match.groups()[0])

        response = self.get(url)
        html = response.html.html
        match = _image_regex.search(html)
        if match:
            return match.groups()[0].replace("&amp;", "&")
        return None

    def extract_image(self, article):
        image_link = self.extract_photo_link(article)
        if image_link is not None:
            return image_link
        return self.extract_image_lq(article)

    def extract_image_lq(self, article):
        story_container = article.find('div.story_body_container', first=True)
        if story_container is None:
            return None
        other_containers = story_container.xpath('div/div')

        for container in other_containers:
            image_container = container.find('.img', first=True)
            if image_container is None:
                continue

            style = image_container.attrs.get('style', '')
            match = _image_regex_lq.search(style)
            if match:
                return utils.decode_css_url(match.groups()[0])

        return None

    def extract_link(self, article):
        html = article.html
        match = _link_regex.search(html)
        if match:
            return utils.unquote(match.groups()[0])
        return None

    def extract_post_url(self, article):
        query_params = ('story_fbid', 'id')

        elements = article.find('header a')
        for element in elements:
            href = element.attrs.get('href', '')
            match = _post_url_regex.match(href)
            if match:
                path = utils.filter_query_params(href, whitelist=query_params)
                return utils.urljoin(self.base_url, path)

        return None

    def login(self, email, password):
        login_page = self.get(self.base_url)
        login_action = login_page.html.find('#login_form', first=True).attrs.get('action')
        self.session.post(
            utils.urljoin(self.base_url, login_action), data={'email': email, 'pass': password}
        )

        if 'c_user' not in self.session.cookies:
            warnings.warn('login unsuccessful')

    def fetch_share_and_reactions(self, post: dict):
        """Fetch share and reactions information with a existing post obtained by `get_posts`.
        Return a merged post that has some new fields including `reactions`, `w3_fb_url`, `fetched_time`,
            and reactions fields `LIKE`, `ANGER`, `SORRY`, `WOW`, `LOVE`, `HAHA` if exist.
        Note that this method will raise one http request per post, use it when you want some more information.
        Example:
        ```
        for post in get_posts('fanpage'):
            more_info_post = fetch_share_and_reactions(post)
            print(more_info_post)
        ```
        """
        url = post.get('post_url')
        if url:
            w3_fb_url = utils.urlparse(url)._replace(netloc='www.facebook.com').geturl()
            resp = self.session.get(w3_fb_url)
            for item in self.parse_share_and_reactions(resp.text):
                data = item['jsmods']['pre_display_requires'][0][3][1]['__bbox']['result'][
                    'data'
                ]['feedback']
                if data['subscription_target_id'] == post['post_id']:
                    return {
                        **post,
                        'shares': data['share_count']['count'],
                        'likes': data['reactors']['count'],
                        'reactions': {
                            reaction['node']['reaction_type'].lower(): reaction['reaction_count']
                            for reaction in data['top_reactions']['edges']
                        },
                        'comments': data['comment_count']['total_count'],
                        'w3_fb_url': data['url'],
                        'fetched_time': datetime.now(),
                    }
        return post

    def parse_share_and_reactions(self, html: str):
        bad_jsons = _shares_and_reactions_regex.findall(html)
        for bad_json in bad_jsons:
            good_json = _bad_json_key_regex.sub(r'\g<prefix>"\g<key>":', bad_json)
            yield json.loads(good_json)
