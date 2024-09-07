import json
import logging
import os
import re
import requests
import textwrap
import uuid
import datetime

from bs4 import BeautifulSoup
from collections import OrderedDict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

EMPTY = 'empty'
TOKEN = os.environ['TG_TOKEN']
ADMIN_ID = os.environ['ADMIN_ID']
BOT_ID = os.environ['BOT_ID']


def strip_markdown(string):
    return string.replace('*', r'\*').replace('_', r'\_').replace('`', r'\`').replace('[', r'\[')


def get_passage(passage, is_amendment=False, inline_details=False):
    SOURCE_URL = 'https://en.wikisource.org/wiki/Constitution_of_the_United_States_of_America'
    if is_amendment:
        SOURCE_URL = 'https://en.wikisource.org/wiki/United_States_Bill_of_Rights'

    try:
        logging.debug('Began fetching from remote')
        result = requests.get(SOURCE_URL).content.decode('utf8')
        logging.debug('Finished fetching from remote')
    except requests.HTTPError as e:
        logging.warning('Error fetching passage:\n' + str(e))
        return 'Error fetching passage.'

    html = result
    start = html.find('<div class="prp-pages-output')
    if start == -1:
        return EMPTY
    end = html.find('<table>', start)  # not sure if consistent/good
    passage_html = html[start:end - 1]

    soup = BeautifulSoup(passage_html, 'lxml')

    # format of html element ids: aIV[-s#][-c#]
    passage_id = 'a' + arabic_to_roman(int(passage[0]))

    title = 'Article ' + passage_id[1:]
    header = '*' + strip_markdown(title.strip()) + '*'

    # need every dd.p in dl after article start
    for tag in soup.select('[id=' + passage_id + '], [id^=' + passage_id + ']'):
        print(tag.text)

    WANTED = 'bg-bot-passage-text'
    # UNWANTED = '.passage-other-trans, .footnote, .footnotes, .crossreference, .cross-refs'

    # for tag in soup.select(UNWANTED):
    #     tag.decompose()

    for tag in soup.select('h1, h2, h3, h4, h5, h6'):
        tag['class'] = WANTED
        text = tag.text.strip()
        if not inline_details:
            text = text.replace(' ', '\a')
        tag.string = '*' + strip_markdown(text) + '*'

    needed_stripping = False

    for tag in soup.select('p'):
        tag['class'] = WANTED
        bad_strings = tag(text=re.compile(r'([*_`\[])'))
        for bad_string in bad_strings:
            stripped_text = strip_markdown(bad_string)
            bad_string.replace_with(stripped_text)
            needed_stripping = True

    if needed_stripping:
        logging.info('Stripped markdown')

    for tag in soup.select('br'):
        tag.name = 'span'
        tag.string = '\n'

    for tag in soup.select('.text'):
        tag.string = tag.text.rstrip()

    final_text = header + '\n\n'
    for tag in soup(class_=WANTED):
        final_text += tag.text.strip() + '\n\n'

    logging.debug('Finished BeautifulSoup processing')

    # if not inline_details:
    return final_text.strip()
    # else:
    #     start = html.find('data-osis="') + 11
    #     end = html.find('"', start)
    #     data_osis = html[start:end]
    #     qr_id = data_osis + '/'
    #     qr_title = title.strip()
    #     content = final_text.split('\n', 1)[1].replace('*', '').replace('_', '')
    #     content = ' '.join(content.split())
    #     qr_description = (content[:150] + '...') if len(content) > 153 else content
    #     return final_text.strip(), qr_id, qr_title, qr_description


def arabic_to_roman(numeral):
    roman = OrderedDict()
    roman[5] = "V"
    roman[4] = "IV"
    roman[1] = "I"

    def roman_num(num):
        for r in roman.keys():
            x, y = divmod(num, r)
            yield roman[r] * x
            num -= (r * x)
            if num <= 0:
                break

    return "".join([a for a in roman_num(numeral)])


# MAX_SEARCH_RESULTS = 5

# def get_search_results(text, start=0):
#     BH_URL = 'http://biblehub.net/search.php?q={}'

#     query = urllib.quote(text.encode('utf-8', 'ignore').lower().strip())
#     url = BH_URL.format(query)
#     try:
#         result = requests.fetch(url, deadline=10)
#     except requests_errors.Error as e:
#         logging.warning('Error fetching search results:\n' + str(e))
#         return None

#     html = result.content
#     soup = BeautifulSoup(html, 'lxml')

#     headers = soup.select('.l')
#     bodies = soup.select('.s')

#     num_results = len(headers)

#     if num_results == 0 or start >= num_results:
#         return EMPTY

#     results_body = ''
#     end = min(num_results, start + MAX_SEARCH_RESULTS)
#     for i in range(start, end):
#         header = headers[i].text

#         idx = header.find(':')
#         idx += header[idx:].find(' ')
#         title = strip_markdown(header[:idx].strip())

#         body = bodies[i]

#         bad_strings = body(text=re.compile('(\*|\_)'))
#         for bad_string in bad_strings:
#             stripped_text = strip_markdown(unicode(bad_string))
#             bad_string.replace_with(stripped_text)

#         for tag in body('b'):
#             if tag.text == u'...':
#                 continue
#             tag.string = '*' + tag.text + '*'

#         body_text = body.text
#         idx = body_text.rfind('//biblehub.com')
#         description = ' '.join(body_text[:idx].split())

#         link = '/' + ''.join(title.split()).lower().replace(':', 'V')

#         results_body += u'\U0001F539' + title + '\n' + description + '\n' + link + '\n\n'

#     final_text = 'Search results'

#     if num_results > MAX_SEARCH_RESULTS:
#         final_text += ' ({}-{} of {})'.format(start + 1, end, num_results)

#     final_text += '\n\n' + results_body.strip()

#     if start + MAX_SEARCH_RESULTS < num_results:
#         final_text += '\n\nGet /more results'

#     return final_text


TELEGRAM_URL = 'https://api.telegram.org/bot' + TOKEN
TELEGRAM_URL_SEND = TELEGRAM_URL + '/sendMessage'
TELEGRAM_URL_CHAT_ACTION = TELEGRAM_URL + '/sendChatAction'
JSON_HEADER = {'Content-Type': 'application/json;charset=utf-8'}

LOG_SENT = '{} {} sent to uid {} ({})'
LOG_ENQUEUED = 'Enqueued {} to uid {} ({})'
LOG_DID_NOT_SEND = 'Did not send {} to uid {} ({}): {}'
LOG_ERROR_SENDING = 'Error sending {} to uid {} ({}):\n{}'
LOG_ERROR_DATASTORE = 'Error reading from datastore:\n'
LOG_ERROR_INVALID_LINK = 'Invalid link! Link: '
LOG_ERROR_INVALID_QUICK = 'Invalid quick lookup! Reference: '
LOG_ERROR_QUERY = 'Error querying uid {} ({}): {}'
LOG_TYPE_START_NEW = 'Type: Start (new user)'
LOG_TYPE_START_EXISTING = 'Type: Start (existing user)'
LOG_TYPE_NON_TEXT = 'Type: Non-text'
LOG_TYPE_NON_MESSAGE = 'Type: Non-message'
LOG_TYPE_NEW_PARTICIPANT = 'Type: New participant'
LOG_UNRECOGNIZED = 'Type: Unrecognized'
LOG_USER_MIGRATED = 'User {} migrated to uid {} ({})'
LOG_USER_DELETED = 'Deleted uid {} ({})'
LOG_USER_REACHABLE = 'Uid {} ({}) is still reachable'
LOG_USER_UNREACHABLE = 'Unable to reach uid {} ({}): {}'

RECOGNIZED_ERROR_PARSE = 'Bad Request: cannot parse'
RECOGNIZED_ERROR_MIGRATE = 'Bad Request: group chat was upgraded to a supergroup chat'
RECOGNIZED_ERRORS = ('PEER_ID_INVALID',
                     'Bot was blocked by the user',
                     'Forbidden: user is deleted',
                     'Forbidden: user is deactivated',
                     'Forbidden: User is deactivated',
                     'Forbidden: bot was blocked by the user',
                     'Forbidden: Bot was blocked by the user',
                     'Forbidden: bot was kicked from the group chat',
                     'Forbidden: bot was kicked from the channel chat',
                     'Forbidden: bot was kicked from the supergroup chat',
                     'Forbidden: bot is not a member of the supergroup chat',
                     'Forbidden: bot can\'t initiate conversation with a user',
                     'Forbidden: Bot can\'t initiate conversation with a user',
                     'Bad Request: chat not found',
                     'Bad Request: PEER_ID_INVALID',
                     'Bad Request: have no rights to send a message',
                     'Bad Request: not enough rights to send text messages to the chat',
                     'Bad Request: group chat was deactivated',
                     RECOGNIZED_ERROR_MIGRATE)


def telegram_post(data, deadline=10):
    return requests.post(TELEGRAM_URL_SEND, data, headers=JSON_HEADER, timeout=deadline)


def telegram_query(uid, deadline=10):
    data = json.dumps({'chat_id': uid, 'action': 'typing'})
    return requests.post(TELEGRAM_URL_CHAT_ACTION, data, headers=JSON_HEADER, timeout=deadline)


class User:  # (db.Model):
    def __init__(self, uname, f_name='', l_name=''):
        self.uid = uuid.uuid4()
        self.username = uname  # db.StringProperty(indexed=False)
        self.first_name = f_name  # db.StringProperty(multiline=True, indexed=False)
        self.last_name = l_name  # db.StringProperty(multiline=True, indexed=False)
        self.created = datetime.today()  # db.DateTimeProperty(auto_now_add=True)
        self.last_received = datetime.today()  # DateTime (auto_now_add=True, indexed=False)
        self.last_sent = datetime.today()  # db.DateTimeProperty(indexed=False)
        self.reply_to = ''  # db.StringProperty(multiline=True, indexed=False)
        self.promo = False  # db.BooleanProperty(default=False)

    def get_uid(self):
        return str(self.uid)

    def get_name_string(self):
        def prep(string):
            return string.encode('utf-8', 'ignore').strip()

        name = prep(self.first_name)
        if self.last_name:
            name += ' ' + prep(self.last_name)
        if self.username:
            name += ' @' + prep(self.username)

        return name

    def get_description(self):
        user_type = 'group' if self.is_group() else 'user'
        return user_type + ' ' + self.get_name_string()

    def is_group(self):
        return int(self.get_uid()) < 0

    def set_promo(self, promo):
        self.promo = promo
        # self.put()

    def update_last_received(self):
        self.last_received = datetime.now()
        # self.put()

    def update_last_sent(self):
        self.last_sent = datetime.now()
        # self.put()

    def await_reply(self, command):
        if command is not None and len(command) > 1500:
            command = command[:1500]
        self.reply_to = command
        # self.put()

    def migrate_to(self, uid):
        # props = dict((prop, getattr(self, prop)) for prop in self.properties().keys())
        # props.update(key_name=str(uid))
        new_user = User(self)  # **props)
        # new_user.put()
        # self.delete()
        return new_user


def get_user(uid):
    # key = db.Key.from_path('User', str(uid))
    # user = db.get(key)
    if True:  # user == None:
        user = User('-', '-')
        # user.put()
    return user


def user_exists(uid):
    # key = db.Key.from_path('User', str(uid))
    # user = db.get(key)
    return False  # user != None


def update_profile(uid, uname, f_name, l_name):
    existing_user = get_user(uid)
    if existing_user:
        existing_user.username = uname
        existing_user.first_name = f_name
        existing_user.last_name = l_name
        existing_user.update_last_received()
        # existing_user.put()
        return existing_user
    else:
        user = User(uname, f_name, l_name)
        # user.put()
        return user


def build_buttons(menu):
    buttons = []
    for item in menu:
        buttons.append([item])
    return buttons


def build_keyboard(buttons):
    return {'keyboard': buttons, 'one_time_keyboard': True}


def build_inline_switch_keyboard(text, query=''):
    inline_switch_button = {'text': text, 'switch_inline_query': query}
    return {'inline_keyboard': [[inline_switch_button]]}


def send_message(user_or_uid, text, msg_type='message', force_reply=False, is_markdown=False,
                 disable_web_page_preview=True, custom_keyboard=None, hide_keyboard=False):
    try:
        uid = str(user_or_uid.get_uid())
        user = user_or_uid
    except AttributeError:
        uid = str(user_or_uid)
        user = get_user(user_or_uid)

    def send_short_message(msg_text):
        build = {
            'chat_id': uid,
            'text': msg_text.replace('\a', ' ')
        }

        if force_reply:
            build['reply_markup'] = dict(force_reply=force_reply)
        elif custom_keyboard:
            build['reply_markup'] = custom_keyboard
        elif hide_keyboard:
            build['reply_markup'] = {'remove_keyboard': hide_keyboard}

        if is_markdown or msg_type in ('passage', 'result'):
            build['parse_mode'] = 'Markdown'

        if disable_web_page_preview:
            build['disable_web_page_preview'] = disable_web_page_preview

        data = json.dumps(build)

        def queue_message():
            payload = json.dumps({
                'msg_type': msg_type,
                'data': data
            })
            requests.post('/message', payload)
            logging.info(LOG_ENQUEUED.format(msg_type, uid, user.get_description()))

        if msg_type == 'promo':
            user.set_promo(True)
            queue_message()
            return

        try:
            result = telegram_post(data)
        except requests.HTTPError as e:
            logging.warning(LOG_ERROR_SENDING.format(msg_type, uid, user.get_description(), str(e)))
            queue_message()
            return

        response = json.loads(result.content)
        error_description = str(response.get('description'))

        if error_description.startswith(RECOGNIZED_ERROR_PARSE):
            if build.get('parse_mode'):
                del build['parse_mode']
            data = json.dumps(build)
            queue_message()

        elif not handle_response(response, user, uid, msg_type):
            queue_message()

    if text.strip() == '':
        return

    if len(text) > 4096:
        chunks = textwrap.wrap(text, 4096, replace_whitespace=False, drop_whitespace=False)
        i = 0
        for chunk in chunks:
            send_short_message(chunk)
            i += 1
    else:
        send_short_message(text)


def handle_response(response, user, uid, msg_type):
    if response.get('ok'):
        msg_id = str(response.get('result').get('message_id'))
        logging.info(LOG_SENT.format(msg_type.capitalize(), msg_id, uid, user.get_description()))
        user.update_last_sent()

    else:
        error_description = str(response.get('description'))
        if error_description.startswith(RECOGNIZED_ERROR_PARSE):
            logging.warning(LOG_ERROR_SENDING.format(msg_type, uid, user.get_description(),
                                                     error_description))
            return True

        if error_description not in RECOGNIZED_ERRORS:
            logging.warning(LOG_ERROR_SENDING.format(msg_type, uid, user.get_description(),
                                                     error_description))
            return False

        logging.info(LOG_DID_NOT_SEND.format(msg_type, uid, user.get_description(),
                                             error_description))
        if error_description == RECOGNIZED_ERROR_MIGRATE:
            new_uid = response.get('parameters', {}).get('migrate_to_chat_id')
            if new_uid:
                user = user.migrate_to(new_uid)
                logging.info(LOG_USER_MIGRATED.format(uid, new_uid, user.get_description()))
        else:
            user_description = user.get_description()
            user.delete()
            logging.info(LOG_USER_DELETED.format(uid, user_description))
            return True

        if msg_type == 'promo':
            user.set_promo(False)

    return True


def send_typing(uid):
    data = json.dumps({'chat_id': uid, 'action': 'typing'})
    try:
        # rpc = requests.create_rpc()
        requests.post(TELEGRAM_URL_CHAT_ACTION, data, headers=JSON_HEADER)
    except requests.HTTPError:
        return


class MainPage(BaseHTTPRequestHandler):
    BOT_USERNAME = 'usconstitutionbot'
    BOT_HANDLE = '@' + BOT_USERNAME
    BOT_DESCRIPTION = 'This bot can fetch US Constitution passages from wikisource.org.'

    CMD_LIST = '/get <article>[:<section>]\n/getAmd <number>\n' + \
               'Examples:\n/get 3:2\n/getAmd 1\n' + \
               'Inline mode:\n' + BOT_HANDLE + ' 3:2\n' + BOT_HANDLE + ' amd1'

    WELCOME_GROUP = 'Hello, friends in {}! Thanks for adding me in!'
    WELCOME_USER = 'Hello, {}! Welcome!'
    WELCOME_GET_STARTED = ' ' + BOT_DESCRIPTION + \
                          '\n\nTo get started, enter one of the following commands:\n' + CMD_LIST

    HELP = 'Hi {}! Please enter one of the following commands:\n' + CMD_LIST + '\n\n' + \
           'Enjoy using Constitution Bot? Click the link below to rate it!\n' + \
           'https://telegram.me/storebot?start=' + BOT_USERNAME

    UNRECOGNIZED = 'Sorry {}, I could not understand that. ' + \
                   'Please enter one of the following commands:\n' + CMD_LIST

    REMOTE_ERROR = 'Sorry {}, I\'m having some difficulty accessing the site. ' + \
                   'Please try again later.'

    GET_PASSAGE = 'Which constitution passage do you want to look up?'

    # GET_SEARCH_TERM = 'Please enter what you wish to search for.\n\n' + \
    #                   'Tip: For faster results, use:\n/search make disciples\n' + \
    #                   '/search "love is patient" _(quotes to match exact phrase)_'

    NO_RESULTS_FOUND = 'Sorry {}, no results were found. Please try again.'
    # VERSION_NOT_FOUND = 'Sorry {}, I could not find that version. ' + \
    #                     'Use /setdefault to view all available versions.'

    SET_DEFAULT_CHOOSE_LANGUAGE = 'Choose a language:'
    # SET_DEFAULT_CHOOSE_VERSION = 'Select a version:'
    # SET_DEFAULT_SUCCESS = 'Success! Default version is now *{}*.'
    # SET_DEFAULT_FAILURE = VERSION_NOT_FOUND + '\n\nCurrent default is *{}*.'

    # SETTINGS = 'Current default version is *{}*. Use /setdefault to change it.'

    BACK_TO_LANGUAGES = u'\U0001F519' + ' to language list'

    TRY_KEYBOARD = build_inline_switch_keyboard('Try inline mode', '3:2')

    def get(self):
        # should I send_response(200)?
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(bytes(self.BOT_USERNAME + ' backend running...\n', 'utf-8'))

    def post(self):
        data = json.loads(self.request.body)
        logging.debug(self.request.body)

        inline_query = data.get('inline_query')
        chosen_inline_result = data.get('chosen_inline_result')

        if inline_query:
            qid = inline_query.get('id')
            query = inline_query.get('query').encode('utf-8', 'ignore')

            if not query:
                results = []
            else:
                words = query.split()
                if len(words) > 1 and words[0].upper() == 'AMD':
                    passage = words[1]
                    response = get_passage(passage, is_amendment=True, inline_details=True)
                else:
                    response = get_passage(query, inline_details=True)

                results = []
                if not response:
                    self.send_error(HTTPStatus.BAD_GATEWAY)  # 502
                elif response == EMPTY:
                    results = []
                else:
                    passage = response[0]
                    qr_id = response[1]
                    qr_title = response[2]
                    qr_description = response[3]
                    content = {'message_text': passage, 'parse_mode': 'Markdown',
                               'disable_web_page_preview': True}
                    results = [{'type': 'article', 'id': qr_id, 'title': qr_title,
                                'description': qr_description, 'input_message_content': content,
                                'thumb_url': ''}]

            # default_version = 'NIV'
            payload = {'method': 'answerInlineQuery', 'inline_query_id': qid, 'results': results,
                       # 'switch_pm_text': 'Default version: ' + default_version,
                       'switch_pm_parameter': 'setdefault', 'cache_time': 0}

            output = json.dumps(payload)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(bytes(output, 'utf-8'))
            logging.info('Answered inline query')
            logging.debug(output)
            return
        elif chosen_inline_result:
            logging.info('Inline query result used')
            logging.debug(str(chosen_inline_result))
            return

        msg = data.get('message')
        if not msg:
            logging.info(LOG_TYPE_NON_MESSAGE)
            return

        msg_chat = msg.get('chat')
        msg_from = msg.get('from')

        uid = str(msg_chat.get('id'))
        first_name = msg_from.get('first_name')
        last_name = msg_from.get('last_name')
        username = msg_from.get('username')

        name = first_name.encode('utf-8', 'ignore').strip()
        text = msg.get('text')
        # raw_text = text
        if text:
            text = text.encode('utf-8', 'ignore')
            logging.info(text)

        if msg_chat.get('type') == 'private':
            group_name = name
            user = update_profile(uid, username, first_name, last_name)
        else:
            group_name = msg_chat.get('title')
            user = update_profile(uid, None, group_name, None)
            group_name = group_name.encode('utf-8', 'ignore')

        # if text == '/bot_family_verification_code':
        #     send_message(user, BOT_FAMILY_HASH)
        #     send_message(ADMIN_ID, 'Bot-family verified! :D')
        #     return

        def get_from_string():
            name_string = name
            if last_name:
                name_string += ' ' + last_name.encode('utf-8', 'ignore').strip()
            if username:
                name_string += ' @' + username.encode('utf-8', 'ignore').strip()
            return name_string

        if user.last_sent is None or text == '/start':
            if user.is_group() and msg.get('new_chat_members'):
                new_chat_member_ids = [str(m.get('id')) for m in msg.get('new_chat_members')]
                if BOT_ID not in new_chat_member_ids:
                    logging.info(LOG_TYPE_NEW_PARTICIPANT)
                    return

            if user.last_sent is None:
                logging.info(LOG_TYPE_START_NEW)
                new_user = True
            else:
                logging.info(LOG_TYPE_START_EXISTING)
                new_user = False

            if user.is_group():
                response = self.WELCOME_GROUP.format(group_name)
            else:
                response = self.WELCOME_USER.format(name)
            response += self.WELCOME_GET_STARTED
            send_message(user, response, msg_type='welcome', custom_keyboard=self.TRY_KEYBOARD)
            user.await_reply(None)

            if new_user:
                if user.is_group():
                    new_alert = 'New group: "{}" via user: {}'.format(group_name, get_from_string())
                else:
                    new_alert = 'New user: ' + get_from_string()
                # send_message(ADMIN_ID, new_alert)

            return

        if text is None:
            logging.info(LOG_TYPE_NON_TEXT)
            migrate_to_chat_id = msg.get('migrate_to_chat_id')
            if migrate_to_chat_id:
                new_uid = migrate_to_chat_id
                user = user.migrate_to(new_uid)
                logging.info(LOG_USER_MIGRATED.format(uid, new_uid, user.get_description()))
            return
        text = text.strip()

        def is_get_command():
            return text.lower().startswith('/get')

        # def is_get_amd_command():
        #     return text.lower().startswith('/getAmd')

        # def is_full_search_command():
        #     return text.lower().startswith('/search ')

        # def is_link_command():
        #     return text[1:].startswith(BOOKS)

        def is_command(word):
            cmd = text.lower().strip()
            short_cmd = ''.join(cmd.split())
            slash_word = '/' + word
            left_pattern = slash_word + self.BOT_HANDLE
            right_pattern = self.BOT_HANDLE + slash_word
            return cmd == slash_word or short_cmd.startswith((left_pattern, right_pattern))

        if is_command('get'):
            user.await_reply('get')
            # is_amendment = user.version
            send_message(user, self.GET_PASSAGE, force_reply=True)

        # elif is_command('search'):
        #     user.await_reply('search')
        #     send_message(user, self.GET_SEARCH_TERM, force_reply=True, markdown=True)

        elif is_get_command():
            user.await_reply(None)
            words = text.split()
            first_word = words[0]

            passage = text[len(first_word) + 1:].strip()
            if not passage:
                user.await_reply(first_word[1:])
                send_message(user, self.GET_PASSAGE, force_reply=True)
                return

            first_passage_word = passage.split()[0].upper()

            if len(first_word) == 4 and passage[len(first_passage_word) + 1:].strip():
                passage = passage[len(first_passage_word) + 1:]

            send_typing(uid)
            response = get_passage(passage, first_passage_word == 'AMD')

            if response == EMPTY:
                send_message(user, self.NO_RESULTS_FOUND.format(name))
                return
            elif response is None:
                send_message(user, self.REMOTE_ERROR.format(name))
                return

            send_message(user, response, 'passage')

        # elif is_full_set_default_command():
        #     user.await_reply(None)
        #     version = text[12:].strip().upper()

        #     if version not in VERSIONS:
        #         send_message(user, self.SET_DEFAULT_FAILURE.format(name, user.version),
        #                      markdown=True)
        #         return

        #     user.update_version(version)
        #     send_message(user, self.SET_DEFAULT_SUCCESS.format(version), markdown=True)

        # elif is_full_search_command():
        #     search_term = raw_text[8:].strip().lower()
        #     user.await_reply('search0 ' + raw_text[8:].strip().lower())

        #     send_typing(uid)
        #     response = get_search_results(search_term)

        #     if response == EMPTY:
        #         user.await_reply(None)
        #         send_message(user, self.NO_RESULTS_FOUND.format(name))
        #         return
        #     elif response == None:
        #         send_message(user, self.REMOTE_ERROR.format(name))
        #         return

        #     send_message(user, response, msg_type='result')

        # elif is_command('setdefault') or raw_text == self.BACK_TO_LANGUAGES or \
        #      text == '/start setdefault':
        #     if text == '/start setdefault':
        #         user.await_reply('setdefault')
        #     buttons = build_buttons(VERSION_DATA.keys())
        #     keyboard = build_keyboard(buttons)
        #     send_message(user, self.SET_DEFAULT_CHOOSE_LANGUAGE, custom_keyboard=keyboard)

        # elif raw_text in VERSION_DATA:
        #     buttons = build_buttons(VERSION_DATA[raw_text] + [self.BACK_TO_LANGUAGES])
        #     keyboard = build_keyboard(buttons)
        #     send_message(user, self.SET_DEFAULT_CHOOSE_VERSION, custom_keyboard=keyboard)

        # elif raw_text in VERSION_LOOKUP:
        #     version = VERSION_LOOKUP[raw_text]
        #     user.update_version(version)
        #     if user.reply_to == 'setdefault':
        #         inline_keyboard = build_inline_switch_keyboard('Back to chat')
        #         send_message(user, self.SET_DEFAULT_SUCCESS.format(version), markdown=True,
        #                      custom_keyboard=inline_keyboard)
        #     else:
        #         send_message(user, self.SET_DEFAULT_SUCCESS.format(version), markdown=True,
        #                      hide_keyboard=True)
        #     user.await_reply(None)

        elif is_command('help'):
            user.await_reply(None)
            send_message(user, self.HELP.format(name), custom_keyboard=self.TRY_KEYBOARD)

        # elif is_command('settings'):
        #     user.await_reply(None)
        #     send_message(user, self.SETTINGS.format(user.version), is_markdown=True)

        # elif is_link_command():
        #     user.await_reply(None)
        #     passage = text[1:].replace('V', ':')
        #     if passage.endswith(self.BOT_HANDLE):
        #         passage = passage[:-len(self.BOT_HANDLE)]

        #     send_typing(uid)
        #     response = get_passage(passage, user.version)

        #     if response == EMPTY:
        #         send_message(user, self.NO_RESULTS_FOUND.format(name))
        #         logging.info(LOG_ERROR_INVALID_LINK + text)
        #         return
        #     elif response == None:
        #         send_message(user, self.REMOTE_ERROR.format(name))
        #         return

        #     send_message(user, response, msg_type='passage')

        # elif text in ('/more', '/more' + self.BOT_HANDLE) and user.reply_to != None and \
        #      user.reply_to.startswith('search') and len(user.reply_to) > 6:
        #     idx = user.reply_to.find(' ')
        #     old_start = int(user.reply_to[6:idx])
        #     search_term = user.reply_to[idx + 1:]

        #     new_start = old_start + MAX_SEARCH_RESULTS

        #     user.await_reply('search{} '.format(new_start) + search_term)

        #     send_typing(uid)
        #     response = get_search_results(search_term, new_start)

        #     if response == EMPTY:
        #         user.await_reply(None)
        #         send_message(user, self.NO_RESULTS_FOUND.format(name))
        #         return
        #     elif response == None:
        #         send_message(user, self.REMOTE_ERROR.format(name))
        #         return

        #     send_message(user, response, msg_type='result')

        # elif user.reply_to != None and user.reply_to == 'search':
        #     search_term = text
        #     user.await_reply('search0 ' + raw_text)

        #     send_typing(uid)
        #     response = get_search_results(search_term)

        #     if response == EMPTY:
        #         user.await_reply(None)
        #         send_message(user, self.NO_RESULTS_FOUND.format(name), hide_keyboard=True)
        #         return
        #     elif response == None:
        #         send_message(user, self.REMOTE_ERROR.format(name), hide_keyboard=True)
        #         return

        #     send_message(user, response, msg_type='result', hide_keyboard=True)

        elif user.reply_to is not None and user.reply_to.startswith('get'):
            is_amendment = user.reply_to[3:].upper() == 'AMD'
            user.await_reply(None)

            send_typing(uid)
            response = get_passage(text, is_amendment)

            if response == EMPTY:
                send_message(user, self.NO_RESULTS_FOUND.format(name), hide_keyboard=True)
                return
            elif response is None:
                send_message(user, self.REMOTE_ERROR.format(name), hide_keyboard=True)
                return

            send_message(user, response, 'passage', hide_keyboard=True)

        else:
            user.await_reply(None)
            msg_reply = msg.get('reply_to_message')
            if user.is_group() and self.BOT_HANDLE not in text and \
                    not (msg_reply and str(msg_reply.get('from').get('id')) == BOT_ID):
                logging.info(LOG_UNRECOGNIZED)
                return

            # to_lookup = text.lower().replace(self.BOT_HANDLE, '')
            # refs = extract_refs(to_lookup)
            # if refs:
            #     ref = refs[0]
            #     book = ref[0]
            #     passage = '{}:{}-{}:{}'.format(book, ref[1], ref[2], ref[3], ref[4])

            #     send_typing(uid)
            #     response = get_passage(passage)

            #     if response == EMPTY:
            #         logging.error(LOG_ERROR_INVALID_QUICK + text)

            #     if response and response != EMPTY:
            #         send_message(user, response, msg_type='passage', hide_keyboard=True)
            #         return

            logging.info(LOG_UNRECOGNIZED)
            send_message(user, self.UNRECOGNIZED.format(name), custom_keyboard=self.TRY_KEYBOARD)


class MessagePage(BaseHTTPRequestHandler):
    def post(self):
        params = json.loads(self.request.body)
        msg_type = params.get('msg_type')
        data = params.get('data')
        uid = str(json.loads(data).get('chat_id'))
        user = get_user(uid)
        result = requests.models.Response()

        try:
            result = telegram_post(data, deadline=30)
        except requests.HTTPError as e:
            logging.warning(LOG_ERROR_SENDING.format(msg_type, uid, user.get_description(), str(e)))
            logging.debug(data)
            self.send_error(HTTPStatus.BAD_GATEWAY)  # 502

        response = json.loads(result.content)

        if not handle_response(response, user, uid, msg_type):
            logging.debug(data)
            self.send_error(HTTPStatus.BAD_GATEWAY)  # 502


class MigratePage(BaseHTTPRequestHandler):
    def get(self):
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(bytes('Migrate page\n', 'utf-8'))


class PromoPage(BaseHTTPRequestHandler):
    # @staticmethod
    # def get():
    #     taskqueue.add(url='/promo')

    def post(self):
        params = json.loads(self.request.body)
        data = params.get('data')
        uid = str(json.loads(data).get('chat_id'))
        user = get_user(uid)
        # three_days_ago = datetime.now() - timedelta(days=3)
        # query = User.all()
        # query.filter('promo =', False)
        # query.filter('created <', three_days_ago)
        # for user in query.run(batch_size=500):
        name = user.first_name.encode('utf-8', 'ignore').strip()
        if user.is_group():
            promo_msg = 'Hello, friends in {}! '.format(name) + \
                        'Do you find Constitution Bot useful?'
        else:
            promo_msg = 'Hi {}, do you find Constitution Bot useful?'.format(name)
        promo_msg += ' Why not rate it on the bot store (you don\'t have to exit Telegram)!\n' + \
                     'https://telegram.me/storebot?start=usconstitutionbot'
        send_message(user, promo_msg, 'promo')


class VerifyPage(BaseHTTPRequestHandler):
    def get(self):
        try:
            # query = User.all()
            # for user in query.run(batch_size=3000):
            # uid = str(user.get_uid())
            # taskqueue.add(url='/verify', payload=uid)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(bytes('Cleanup in progress\n', 'utf-8'))
        except Exception as e:
            logging.error(e)

    def post(self):
        uid = self.request.body
        user = get_user(uid)
        result = {}
        try:
            result = telegram_query(uid, 30)
        except Exception as e:
            logging.warning(LOG_ERROR_QUERY.format(uid, user.get_description(), str(e)))
            self.send_error(HTTPStatus.BAD_GATEWAY)  # 502

        response = json.loads(result.content)

        if response.get('ok'):
            logging.info(LOG_USER_REACHABLE.format(uid, user.get_description()))
        else:
            error_description = str(response.get('description'))
            if error_description == RECOGNIZED_ERROR_MIGRATE:
                new_uid = response.get('parameters', {}).get('migrate_to_chat_id')
                if new_uid:
                    user = user.migrate_to(new_uid)
                    logging.info(LOG_USER_MIGRATED.format(uid, new_uid, user.get_description()))
            elif error_description in RECOGNIZED_ERRORS:
                user_description = user.get_description()
                # user.delete()
                logging.info(LOG_USER_DELETED.format(uid, user_description))
            else:
                logging.warning(LOG_USER_UNREACHABLE.format(uid, user.get_description(),
                                                            error_description))
                self.send_error(HTTPStatus.BAD_GATEWAY)  # 502


app_handler = [
     ('/', MainPage),
     ('/' + TOKEN, MainPage),
     ('/message', MessagePage),
     ('/promo', PromoPage),
     ('/migrate', MigratePage),
     ('/verify', VerifyPage),
]
