# US Constitution Bot (@usconstitutionbot)
Telegram bot that fetches United States Constitution text and amendments from [WikiSource](https://wikisource.org).

## Usage
`/get <article>[:<section>]`

`/getAmd <number>`

### Examples:
`/get 3:2 gets Article 3, Section 2`

`/getAmd 1 gets the First Amendment`

## Todo
* Add amendments past 10
* Include Constitution text as a flat file for more precise searching?
* Add menu/button querying
* Better error handling
* Parse out cmds intended for other bots
* Add linting/auto-format
* Add db for caching user info?
* Add start/welcome message