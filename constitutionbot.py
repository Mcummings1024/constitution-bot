import json
import logging
import os
import re
import requests
import textwrap
import uuid
import datetime

from bs4 import BeautifulSoup
from datetime import datetime
from functools import wraps
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

TG_TOKEN = os.environ['TG_TOKEN']
ADMIN_ID = os.environ['ADMIN_ID']
BOT_ID = os.environ['BOT_ID']
WHITELIST_IDS = [int(id_string) for id_string in os.environ['WHITELIST_IDS'].split(',')]

# region text constants
EMPTY = 'empty'

TELEGRAM_URL = 'https://api.telegram.org/bot' + TG_TOKEN
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
# endregion


def restricted(func):
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in WHITELIST_IDS:
            print("Unauthorized access denied for {}.".format(user_id))
            return
        return func(update, context, *args, **kwargs)
    return wrapped


def strip_markdown(string):
    return string.replace('*', r'\*').replace('_', r'\_').replace('`', r'\`').replace('[', r'\[')


def get_passage(article, is_amendment=False):
    # adjusted to account for two original amendments at the beginning
    ordinals = ['second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth']
    SOURCE_URL = 'https://en.wikisource.org/wiki/Constitution_of_the_United_States_of_America'
    if is_amendment:
        SOURCE_URL = 'https://en.wikisource.org/wiki/United_States_Bill_of_Rights'

    try:
        logging.debug('Began fetching from remote')
        html = requests.get(SOURCE_URL).content.decode('utf8')
        logging.debug('Finished fetching from remote')
    except requests.HTTPError as e:
        logging.warning('Error fetching passage:\n' + str(e))
        return 'Error fetching passage.'

    # not sure if consistent/good
    start = html.find('<div class="prp-pages-output')
    end = html.find('<table>', start)

    if is_amendment:
        start = html.find('Article the twelfth')

        if int(article) < 10:
            start = html.find('Article the {}'.format(ordinals[int(article)]))

        end = html.find('</tr>', start)

    passage_html = html[start:end - 1]
    soup = BeautifulSoup(passage_html, 'html.parser')

    if is_amendment:
        title = 'Amendment {}'.format(article)
        selector = 'td'
    else:
        # format of html element ids: aIV[-s#][-c#]
        article_id = 'a' + arabic_to_roman(int(article[0])) + '-s' + article[2]
        title = 'Article {} Section {}'.format(article_id[1], article[2])

        # need every dd.p in dl after article start
        selector = '[id=' + article_id + '], [id^=' + article_id + ']'

    header = '**' + strip_markdown(title.strip()) + '**'

    # for tag in soup.select(selector):
    #     print(tag.text)

    WANTED = 'bg-bot-passage-text'
    needed_stripping = False

    for tag in soup.select(selector):
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

    return final_text.strip()


def arabic_to_roman(numeral):
    roman = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']
    return roman[numeral-1]  # :trollface:


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
            requests.post(TELEGRAM_URL_SEND, data, headers=JSON_HEADER, timeout=10)
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


@restricted
async def main_cmd(update: Update, context: CallbackContext):
    # region constants
    BOT_USERNAME = 'usconstitutionbot'
    BOT_HANDLE = '@' + BOT_USERNAME
    BOT_DESCRIPTION = 'This bot can fetch US Constitution passages from [WikiSource](wikisource.org).'

    CMD_LIST = '/get <article>[:<section>]\n/getAmd <number>\nExamples:\n/get 3:2\n/getAmd 1\n' + \
               'Inline mode:\n' + BOT_HANDLE + ' 3:2\n' + BOT_HANDLE + ' amd1'

    WELCOME_GROUP = 'Hello, friends in {}! Thanks for adding me in!'
    WELCOME_USER = 'Hello, {}! Welcome!'
    WELCOME_GET_STARTED = ' ' + BOT_DESCRIPTION + \
                          '\n\nTo get started, enter one of the following commands:\n' + CMD_LIST

    HELP = 'Hi {}! Please enter one of the following commands:\n' + CMD_LIST + '\n\n' + \
           'Enjoy using Constitution Bot? Click the link below to rate it!\n' + \
           'https://telegram.me/storebot?start=' + BOT_USERNAME

    UNRECOGNIZED = '{}, that command didn\'t make any fucking sense. ' + \
                   'Please enter one of the following commands:\n' + CMD_LIST

    REMOTE_ERROR = 'Sorry {}, I\'m having some difficulty accessing the site. ' + \
                   'Please try again later.'

    GET_PASSAGE = 'Which constitution passage do you want to look up?'
    NO_RESULTS_FOUND = 'Sorry {}, no results were found. Please try again.'
    # BACK_TO_LANGUAGES = u'\U0001F519' + ' to language list'
    TRY_KEYBOARD = build_inline_switch_keyboard('Try inline mode', '3:2')
    # endregion

    inline_query = ''
    if update['message'] is not None and update.message['text'] is not None:
        inline_query = update.message.text

    chosen_inline_result = update.chosen_inline_result

    if inline_query:
        words = inline_query.strip().split()

        if len(words) > 1 and words[0].upper() == '/GETAMD':
            response = get_passage(words[1], True)
        else:
            response = get_passage(words[1])

        results = []

        if not response:
            logging.error(HTTPStatus.BAD_GATEWAY)  # 502
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

        payload = {'method': 'answerInlineQuery', 'results': results,
                   'switch_pm_parameter': 'setdefault', 'cache_time': 0}

        output = json.dumps(payload)

        if len(response) > 4096:
            response = response[:4093] + '...'

        await context.bot.send_message(update.message.chat_id, response,
                                       reply_to_message_id=update.message.id)
        logging.info('Answered inline query')
        logging.debug(output)
        return
    elif chosen_inline_result:
        logging.info('Inline query result used')
        logging.debug(str(chosen_inline_result))
        return

    msg = update.message

    if not msg:
        logging.info(LOG_TYPE_NON_MESSAGE)
        return

    msg_chat = msg.chat
    msg_from = msg.from_user
    text = msg.text

    uid = str(msg_chat.id)
    first_name = msg_from.first_name
    last_name = msg_from.last_name
    username = msg_from.username
    name = first_name.encode('utf-8', 'ignore').strip()

    if text:
        text = text.encode('utf-8', 'ignore')
        # logging.info(text)

    if msg_chat.type == 'private':
        group_name = name
        user = update_profile(uid, username, first_name, last_name)
    else:
        group_name = msg_chat.title
        user = update_profile(uid, None, group_name, None)
        group_name = group_name.encode('utf-8', 'ignore')

    def get_from_string():
        name_string = name

        if last_name:
            name_string += ' ' + last_name.encode(errors='ignore').strip()

        if username:
            name_string += ' @' + username.encode(errors='ignore').strip()

        return name_string

    if user.last_sent is None or text == '/start':
        if user.is_group() and msg.new_chat_members:
            new_chat_member_ids = [str(m.id) for m in msg.new_chat_members]
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
            response = WELCOME_GROUP.format(group_name)
        else:
            response = WELCOME_USER.format(name)

        response += WELCOME_GET_STARTED
        send_message(user, response, 'welcome', custom_keyboard=TRY_KEYBOARD)
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
        migrate_to_chat_id = msg.migrate_to_chat_id

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

    def is_command(word):
        cmd = text.lower().strip()
        short_cmd = ''.join(cmd.split())
        slash_word = '/' + word
        left_pattern = slash_word + BOT_HANDLE
        right_pattern = BOT_HANDLE + slash_word
        return cmd == slash_word or short_cmd.startswith((left_pattern, right_pattern))

    if is_command('get'):
        user.await_reply('get')
        send_message(user, GET_PASSAGE, force_reply=True)
    elif is_get_command():
        user.await_reply(None)
        words = text.split()
        first_word = words[0]

        passage = text[len(first_word) + 1:].strip()
        if not passage:
            user.await_reply(first_word[1:])
            send_message(user, GET_PASSAGE, force_reply=True)
            return

        first_passage_word = passage.split()[0].upper()

        if len(first_word) == 4 and passage[len(first_passage_word) + 1:].strip():
            passage = passage[len(first_passage_word) + 1:]

        send_typing(uid)
        response = get_passage(passage, first_passage_word == 'AMD')

        if response == EMPTY:
            send_message(user, NO_RESULTS_FOUND.format(name))
            return
        elif response is None:
            send_message(user, REMOTE_ERROR.format(name))
            return

        send_message(user, response, 'passage')
    elif is_command('help'):
        user.await_reply(None)
        send_message(user, HELP.format(name), custom_keyboard=TRY_KEYBOARD)

    # elif is_command('settings'):
    #     user.await_reply(None)
    #     send_message(user, self.SETTINGS.format(user.version), is_markdown=True)

    elif user.reply_to is not None and user.reply_to.startswith('get'):
        is_amendment = user.reply_to[3:].upper() == 'AMD'
        user.await_reply(None)

        send_typing(uid)
        response = get_passage(text, is_amendment)

        if response == EMPTY:
            send_message(user, NO_RESULTS_FOUND.format(name), hide_keyboard=True)
            return
        elif response is None:
            send_message(user, REMOTE_ERROR.format(name), hide_keyboard=True)
            return

        send_message(user, response, 'passage', hide_keyboard=True)
    else:
        user.await_reply(None)
        msg_reply = msg.reply_to_message
        if user.is_group() and BOT_HANDLE not in text and \
                not (msg_reply and str(msg_reply.from_user.id) == BOT_ID):
            logging.info(LOG_UNRECOGNIZED)
            return

        logging.info(LOG_UNRECOGNIZED)
        send_message(user, UNRECOGNIZED.format(name), custom_keyboard=TRY_KEYBOARD)


@restricted
async def message_cmd(update: Update, context: CallbackContext):
    msg_type = 'message'
    data = update.message
    uid = str(data.chat_id)
    user = get_user(uid)
    result = requests.models.Response()

    try:
        result = telegram_post(data, deadline=30)
    except requests.HTTPError as e:
        logging.warning(LOG_ERROR_SENDING.format(msg_type, uid, user.get_description(), str(e)))
        logging.debug(data)
        logging.error(HTTPStatus.BAD_GATEWAY)  # 502

    response = json.loads(result.content)

    if not handle_response(response, user, uid, msg_type):
        logging.debug(data)
        logging.error(HTTPStatus.BAD_GATEWAY)  # 502


@restricted
class MigratePage(BaseHTTPRequestHandler):
    def get(self):
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(bytes('Migrate page\n', 'utf-8'))


@restricted
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


@restricted
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
     CommandHandler('get', main_cmd),
     CommandHandler('getAmd', main_cmd),
     CommandHandler('message', message_cmd),
     # CommandHandler('/promo', PromoPage),
     # CommandHandler ('/migrate', MigratePage),
     # CommandHandler('/verify', VerifyPage),
]
