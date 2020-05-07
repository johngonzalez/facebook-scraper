import codecs
import itertools
import json
import re
from datetime import datetime
from urllib import parse as urlparse

from .item_factory import ItemFactory


_likes_regex = re.compile(r'like_def[^>]*>([0-9,.]+)')
_comments_regex = re.compile(r'cmt_def[^>]*>([0-9,.]+)')
_shares_regex = re.compile(r'([0-9,.]+)\s+Shares', re.IGNORECASE)
_link_regex = re.compile(r"href=\"https:\/\/lm\.facebook\.com\/l\.php\?u=(.+?)\&amp;h=")

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


class PostFactory(ItemFactory):
    @classmethod
    def make_item(cls, node, base_url):
        article = node
        text, post_text, shared_text = cls.extract_text(article)

        return {
            'post_id': cls.extract_post_id(article),
            'text': text,
            'post_text': post_text,
            'shared_text': shared_text,
            'time': cls.extract_time(article),
            'image': cls.extract_image(article),
            'likes': cls.find_and_search(article, 'footer', _likes_regex, cls.parse_int),
            'comments': cls.find_and_search(article, 'footer', _comments_regex, cls.parse_int),
            'shares': cls.find_and_search(article, 'footer', _shares_regex, cls.parse_int),
            'post_url': cls.extract_post_url(article, base_url),
            'link': cls.extract_link(article),
        }

    @classmethod
    def extract_post_id(cls, article):
        try:
            data_ft = json.loads(article.attrs['data-ft'])
            return data_ft['mf_story_key']
        except (KeyError, ValueError):
            return None

    @classmethod
    def extract_text(cls, article):
        # Open this article individually because not all content is fully loaded when skimming through pages
        # This ensures the full content can be read

        nodes = article.find('p, header')
        if nodes:
            post_text = []
            shared_text = []
            ended = False
            for node in nodes[1:]:
                if node.tag == "header":
                    ended = True

                if not ended:
                    post_text.append(node.text)
                else:
                    shared_text.append(node.text)

            text = '\n'.join(itertools.chain(post_text, shared_text))
            post_text = '\n'.join(post_text)
            shared_text = '\n'.join(shared_text)

            return text, post_text, shared_text

        return None, None, None

    @classmethod
    def extract_time(cls, article):
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

    @classmethod
    def extract_image(cls, article):
        return cls.extract_image_lq(article)

    @classmethod
    def extract_image_lq(cls, article):
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
                return cls.decode_css_url(match.groups()[0])

        return None

    @classmethod
    def extract_link(cls, article):
        html = article.html
        match = _link_regex.search(html)
        if match:
            return urlparse.unquote(match.groups()[0])
        return None

    @classmethod
    def extract_post_url(cls, article, base_url):
        query_params = ('story_fbid', 'id')

        elements = article.find('header a')
        for element in elements:
            href = element.attrs.get('href', '')
            match = _post_url_regex.match(href)
            if match:
                path = cls.filter_query_params(href, whitelist=query_params)
                return f'{base_url}{path}'

        return None

    @classmethod
    def decode_css_url(cls, url):
        url = re.sub(r'\\(..) ', r'\\x\g<1>', url)
        url, _ = codecs.unicode_escape_decode(url)
        return url

    @classmethod
    def filter_query_params(cls, url, whitelist=None, blacklist=None):
        def is_valid_param(param):
            if whitelist is not None:
                return param in whitelist
            if blacklist is not None:
                return param not in blacklist
            return True  # Do nothing

        parsed_url = urlparse.urlparse(url)
        query_params = urlparse.parse_qsl(parsed_url.query)
        query_string = urlparse.urlencode([(k, v) for k, v in query_params if is_valid_param(k)])
        return urlparse.urlunparse(parsed_url._replace(query=query_string))

    @classmethod
    def parse_share_and_reactions(cls, html):
        bad_jsons = _shares_and_reactions_regex.findall(html)
        for bad_json in bad_jsons:
            good_json = _bad_json_key_regex.sub(r'\g<prefix>"\g<key>":', bad_json)
            yield json.loads(good_json)
