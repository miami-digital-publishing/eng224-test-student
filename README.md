# Your Game Manual Website

This repository holds the files for your game manual. Every time you **commit** (save your changes to GitHub), a tool called DITA-OT turns your files into a website automatically.

**Your website's address** is in the **About** box on the right side of this page (on a phone, scroll down to find it). Bookmark it!

---

## 1. Open the editor

1. Go to this repository's page on github.com (the page you're reading now).
2. Press the **.** (period) key on your keyboard.

The editor, **github.dev**, opens in your browser. It looks like a word processor's file list on the left and your writing on the right. You don't need to install anything.

> If the period key doesn't work, change `github.com` to `github.dev` in the address bar and press Enter.

## 2. Know your files

| File or folder | What it is |
|---|---|
| `manual.md` | Your website's **menu**. It lists every page, in order. |
| `topics/` | Your **pages**. Each page is one `.md` file. |
| `images/` | Your **pictures**. |
| `design.md` | Your website's **look**: theme, colors, and fonts. |
| `.github/` | The website builder. **Don't change anything in here.** |

The Tic-Tac-Toe pages are examples. Look at them to see how each kind of page works, then replace them with your own game.

## 3. Write a page (a "topic")

Every page starts with a title line: a `#`, a space, the title, and the **topic type** in curly brackets.

```
# Setting Up the Board {.task}
```

There are three topic types:

**Concept** `{.concept}` explains *what something is*. Use paragraphs. Use `##` for section headings.

```
# How Scoring Works {.concept}

Players earn points by building settlements and cities.

## Bonus points

The longest road is worth two extra points.
```

**Task** `{.task}` explains *how to do something*. Use a numbered list, with **one instruction per number**. To add details to a step, use a bullet point indented under it.

```
# Set Up the Board {.task}

Do this before your first game.

1. Lay out the ten land tiles in a circle.
2. Shuffle the development cards.
    - Place them face down beside the board.
3. Give each player a set of pieces.

The board is ready for play.
```

**Reference** `{.reference}` holds *facts to look up*, usually in a table.

```
# Building Costs {.reference}

| Item | Cost |
|------|------|
| Road | 1 brick, 1 wood |
| City | 3 ore, 2 wheat |
```

### Add a new page

1. In the file list, right-click the **topics** folder and choose **New File**.
2. Name it with **lowercase letters and hyphens only**, ending in `.md`. For example, `trading-resources.md`. No spaces!
3. Write or paste your content.
4. Add the page to your menu (next section). **A page that isn't in the menu won't appear on your website.**

## 4. Edit the menu (`manual.md`)

`manual.md` is a bulleted list of links. Each link looks like this:

```
- [The words shown in the menu](topics/the-file-name.md)
```

To group pages under a heading, write the heading as a bullet **without** a link, then indent the pages under it by pressing **Tab**:

```
# Catan Game Manual

- [About the game](topics/about.md)
- Getting started
    - [What's in the box](topics/components.md)
    - [Set up the board](topics/set-up.md)
- [Glossary](topics/glossary.md)
```

The first line, starting with `#`, is your website's title.

## 5. Add a picture

1. Drag the picture file from your computer onto the **images** folder in the file list.
2. Rename it with lowercase letters and hyphens, like `starting-board.png`.
3. In your page, add this line where the picture should go:

```
![A short description of the picture](../images/starting-board.png)
```

The description is read aloud to people who use screen readers, so make it meaningful. The `../` at the start means "go up one folder"; it's needed because your pages are inside the topics folder.

## 6. Change your website's look (`design.md`)

Open `design.md` and change the words after the colons:

```
Theme: ocean
Main color: navy
Heading font: Merriweather
```

The instructions in `design.md` list every theme and setting. You can't break your website from this file: if the builder doesn't understand something, it uses the theme's normal setting and tells you in the build report.

## 7. Publish your changes (commit)

Your website **doesn't change until you commit.**

1. Click the **Source Control** icon on the far left. It looks like a branching line, and shows a number when you have changes.
2. Type a short message describing what you changed, like `Add setup page`.
3. Click **Commit & Push**.
4. Wait about **two minutes**, then open your website and refresh the page.

Check the **"Last updated"** time at the bottom of any page on your website. If it shows the time of your latest commit, you're looking at the newest version. If not, wait a minute and refresh again.

## 8. If something goes wrong

The builder fixes small mistakes for you and builds your website whenever it can.

- **Build report:** the bottom of every page on your website has a **Build report** link. It lists anything that needs your attention, like a menu link that points to a file that doesn't exist, or a picture that's missing.
- **"Your website didn't update" email:** if the builder can't build your website at all, it opens an **Issue** in this repository, and GitHub emails you. The issue explains the problem in plain English. It closes by itself once you fix the problem and commit again.
- **The Actions tab:** at the top of this repository's page on github.com, **Actions** shows every build. A green check ✅ means it worked; a red ✖️ means it didn't. Click one to see its report.

---

## Tips for working with an AI

Paste these rules into your AI chat before asking it to convert a section of your rulebook:

```
Format your answer as Markdown DITA (MDITA) for a DITA-OT website:
- Start with one title line: "# Title {.concept}", "# Title {.task}", or "# Title {.reference}".
- Concept: explains what something is. Paragraphs, with "##" section headings if needed.
- Task: explains how to do something. A short intro sentence, then a numbered list
  with ONE instruction per number. Put extra details as "-" bullets indented under
  a step. Never put a paragraph, picture, or note inside a numbered step.
- Reference: facts to look up, in Markdown tables.
- Write one topic per answer. Don't add YAML front matter or HTML.
```

Remember: the AI is your assistant, not the author. Check every rule against the original rulebook.
