import logging
import os

from argparse import ArgumentParser
from constitutionbot import app_handler
from telegram import Update
from telegram.ext import (
    filters,
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    MessageHandler,
)
from typing import List, Optional, Set


def main() -> None:
    parser = ArgumentParser(description='Runs TG bot')

    if 'TG_TOKEN' not in os.environ:
        parser.add_argument(
            'token', action='store', type=str, help='Telegram Token for the bot')

    whitelist_group = parser.add_mutually_exclusive_group(required=True)
    whitelist_group.add_argument(
        '--uid', action='append', dest='whitelist', metavar='Telegram User ID',
        type=int, help='Telegram User IDs authorized to use this bot')
    whitelist_group.add_argument(
        '--no-whitelist', action='store_const', const=None, dest='whitelist',
        help='Allow all Telegram Users to use this bot (Could cause rate limiting by Meta)')
    login = parser.add_mutually_exclusive_group(required=True)
    login.add_argument(
        '--no-login', action='store_const', const=None, dest='ig_user',
        help='Runs without an Instagram account (Not recommended, quickly limited)')
    login.add_argument(
        '--user', action='store', dest='ig_user', metavar='Instagram User',
        type=str, help='Username through which Instaloader is ran')
    parser.add_argument(
        '--no-rich', action='store_false', dest='rich', help='Disables rich output')
    parser.add_argument(
        '--log-file', action='store_true', dest='logfile', help='Log to file')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable Debug mode')

    args = parser.parse_args()

    logging_handlers: List[logging.Handler] = []
    do_rich = False
    if args.rich:
        try:
            from rich.logging import RichHandler
        except ImportError:
            logging_handlers.append(logging.StreamHandler())
        else:
            logging_handlers.append(RichHandler(rich_tracebacks=True))
            do_rich = True
    else:
        logging_handlers.append(logging.StreamHandler())

    if args.logfile:
        logging_handlers.append(logging.FileHandler('IgTgBot.log'))

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=logging_handlers,
    )

    logging.info(args)
    logging.info('do_rich: %s', do_rich)

    if args.whitelist is None:
        user_whitelist: Optional[Set[int]] = None
        logging.info('No authorized users specified')
    else:
        user_whitelist = set(args.whitelist)
        logging.info('Authorized users: %s', user_whitelist)

    token = os.environ['TG_TOKEN']
    application = Application.builder().token(token).build()

    application.add_handlers(app_handler)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    # application.add_handler(InlineQueryHandler(app_handler.inline_query))
    # application.add_error_handler(error_handler.error_handler)

    application.run_polling()


async def start(update: Update, context: CallbackContext) -> None:
    if update.message is None:
        raise ValueError('Expected update.message to not be None.')
    await update.message.reply_text('Hi, lmao', quote=True)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id=update.effective_chat.id,
                                   text='Learn English idiot, that command made no sense!')


if __name__ == '__main__':
    main()
