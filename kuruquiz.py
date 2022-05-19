from random import randint, choice
from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql.expression import func, select
import psycopg2
import asyncio
import hikari
import lightbulb
import re
import os

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL').replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

bot = lightbulb.BotApp(token=DISCORD_TOKEN, default_enabled_guilds=(799471328078856212, 812565163664343080))


class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    quote = db.Column(db.String(500), unique=True, nullable=False)


@bot.listen(lightbulb.CommandErrorEvent)
async def on_error(event: lightbulb.CommandErrorEvent) -> None:
    if isinstance(event.exception, lightbulb.CommandInvocationError):
        await event.context.respond(
            f"Something went wrong during invocation of command `{event.context.command.name}`.")
        raise event.exception
    exception = event.exception.__cause__ or event.exception
    if isinstance(exception, lightbulb.errors.MissingRequiredRole):
        await event.context.respond("You are missing one or more roles required in order to run this command.")


def get_quote():
    """Returns a random quote from quotes.txt and also splits it."""
    random_quote = Quote.query.order_by(func.random()).first()
    sub_quote_marks = re.sub(r"'([^A-Za-z])", r"\1", re.sub(r"([^A-Za-z])'", r"\1", random_quote.quote))
    quote_as_list = list(filter(None, re.split('[., \-!?:;~/*"\[\]]+', sub_quote_marks)))
    return random_quote.quote, quote_as_list


@bot.command()
@lightbulb.option("key", "Search for a keyword or quote number.", required=False, )
@lightbulb.command("quote", "See a random Kuru Quote!")
@lightbulb.implements(lightbulb.SlashCommand)
async def quote(message):
    with open('quotes.txt') as f:
        quotes = f.readlines()
        if message.options.key is None:
            random_quote = choice(quotes)
            await message.respond(random_quote)
        elif message.options.key.isnumeric():
            await message.respond(quotes[int(message.options.key) - 1])
        elif message.options.key:
            try:
                matching_lines = [quote for quote in quotes if re.search(fr'\b{message.options.key.lower()}', quote.lower())]
                await message.respond(choice(matching_lines))
            except IndexError:
                await message.respond(f"No result for keyword '{message.options.key}'")



@bot.command()
@lightbulb.add_checks(lightbulb.has_roles(role1=799578859850563604))
@lightbulb.option("quote", "The quote to add.")
@lightbulb.command("addquote", "Adds a quote to the database.")
@lightbulb.implements(lightbulb.SlashCommand)
async def addquote(message):
    with open('quotes.txt', 'a') as quotes:
        quotes.write(f"\n{message.options.quote}")
        await message.respond(f"Added quote: {message.options.quote}")


@bot.command()
@lightbulb.add_checks(lightbulb.has_roles(role1=799578859850563604))
@lightbulb.option("key", "The quote number or __**exact**__ quote to delete.")
@lightbulb.command("delquote", "Deletes a quote form the database.")
@lightbulb.implements(lightbulb.SlashCommand)
async def delquote(message):
    with open("quotes.txt", "r+") as f:
        old_f = f.readlines()
        new_f = []
        f.seek(0)
        if message.options.key.isnumeric():
            for line in old_f:
                if line != old_f[int(message.options.key) - 1]:
                    new_f.append(line)
                else:
                    await message.respond(f"Deleted quote #{old_f.index(line) + 1}: {line}")
        else:
            for line in old_f:
                if line.strip("\n") != message.options.key:
                    new_f.append(line)
                else:
                    await message.respond(f"Deleted quote #{old_f.index(line) + 1}: {line}")
        new_f[-1] = new_f[-1].rstrip('\r\n')
        f.writelines(new_f)
        f.truncate()


def get_word(quote):
    """Takes quote and returns a random word."""
    random_word = choice(quote)
    while random_word == "Kururin" or len(random_word) < 3:
        random_word = choice(quote)
    return random_word


def censor_quote(quote, random_word):
    """Takes quote and word, then returns the quote with the word censored."""
    censored_word = "".join(['\_' for char in random_word])

    censored_quote = re.sub(fr'\b{random_word}\b', censored_word, quote)
    return censored_quote


def reformat_quote(quote, random_word):
    reformatted_word = f"__**{random_word}**__"

    reformatted_quote = re.sub(fr'\b{random_word}\b', reformatted_word, quote)
    return reformatted_quote


@bot.command()
@lightbulb.command("begin", "Start game!")
@lightbulb.implements(lightbulb.SlashCommand)
async def begin(message):
    game_over = False
    lives = 3
    correct = 0
    quotes_this_session = []
    await message.respond("Welcome to the Kuru Quote Quiz! Test your knowledge of Kururin quotes by guessing the missing word. Your "
          "goal is to correctly guess five quotes and you have three lives.")

    while not game_over:
        random_quote = get_quote()
        while random_quote[0] in quotes_this_session:
            random_quote = get_quote()
        quotes_this_session.append(random_quote[0])
        random_word = get_word(random_quote[1])

        await message.respond(f"{censor_quote(random_quote[0], random_word)}\n Guess the missing word: ")

        def check(m):
            return m.author == message.author
        try:
            guess = await bot.wait_for(hikari.events.MessageCreateEvent, timeout=30, predicate=check)
        except asyncio.TimeoutError:
            await message.respond("Oops, no response detected for 30 seconds. Quiz timed out!")
            return
        else:
            guess = guess.content
            if guess.lower() == random_word.strip(',.?!*:!"-').lower():
                correct += 1
                await message.respond(f"{reformat_quote(random_quote[0], random_word)}\nYou got it!")
                if correct == 5:
                    game_over = True
                    await message.respond(f"You got {correct} quotes correct and had {lives} lives remaining! Gaming warlord!")
            else:
                lives -= 1
                await message.respond(f"Nope, wrong answer. You have {lives} lives remaining!\nThe correct quote was: {reformat_quote(random_quote[0], random_word)}")
                if lives == 0:
                    game_over = True
                    await message.respond(f"You are out of lives, just like Kururin playing Yoshi's Island :(  Game over!")

bot.run()
