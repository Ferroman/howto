---
name: howto-video
description: Make a narrated how-to video of a web app with the `howto` command. Use when the user asks for a how-to video, a product walkthrough or a screencast of a task in a browser app, or wants to change or re-record one. You explore the app with `howto probe`, write a storyboard file, and `howto render` produces the video.
---

# How-to videos with `howto`

You write a storyboard: a YAML file that says where the video starts, what to do and what to say. The `howto` command performs it in its own browser, records it, speaks the narration and writes an MP4 with subtitle files.

You never click anything yourself, and you never see the screen. `howto probe` describes each page to you as text.

## What you need from the user

Ask for anything that is missing before you start.

- **The task**, in one sentence: "show how to invite a teammate".
- **The start URL** of the app.
- **The profile name**, if the app needs a sign-in. The user creates the profile once with `howto login NAME URL`, which opens a browser window for them. You cannot sign in, and you must not ask for a password.
- **Where the storyboard goes.** The default is `videos/SHORT-NAME.yaml` in the current project.

Every probe and every take performs its actions for real. Before you run anything that creates, sends or deletes, confirm with the user that the profile is signed in to a demo workspace or a test account.

## The loop

1. Write the file with `title`, `url`, `profile` and a `setup` that waits for something only a signed-in user sees, for example the main heading of the start page. Add one first step.
2. Run `howto probe FILE`. Read the outline at the end. It lists the elements of the page by role and name.
3. Add the next step. Use each name exactly as the outline prints it.
4. Probe again. A line `step N FAILED` gives the action and the reason.
   - `0 elements match`: the name is wrong. Find the right one in the outline.
   - `2 elements match` (or more): the locator is ambiguous. Add `exact: true`, `nth` or `within`.
5. Repeat until the task is complete and every step prints `ok`.
6. If the steps change data, add `cleanup` actions that undo the change, and probe once more.
7. Run `howto render FILE`. It prints the paths of the video and the two subtitle files.
8. Report those paths and the list of steps to the user.

Two options help with a large page:

- `howto probe FILE --within '{role: dialog}'` limits the outline to one element.
- `howto probe FILE --until 2` stops after step 2, so you see an earlier page.

## Storyboard

```yaml
title: Invite a teammate
url: https://app.example.com
profile: demo
setup:
  - wait_for: {role: button, name: Settings}
steps:
  - chapter: Invite a teammate
  - say: Open Settings, where teammates are managed.
    do:
      - click: {role: button, name: Settings}
  - say: Type your teammate's email, then press Invite.
    note: The invitation is valid for seven days.
    do:
      - fill: {label: Email address, value: sam@example.com}
      - click: {role: button, name: Invite}
cleanup:
  - click: {role: button, name: Revoke invitation}
```

| Top-level field | Meaning |
|---|---|
| `title`, `url`, `steps` | Required |
| `profile` | The signed-in browser profile. Without it the browser is fresh and signed out |
| `setup` | Actions before recording starts |
| `cleanup` | Actions after recording stops |
| `viewport` | `1920x1080` by default. Both numbers must be even |

| Step field | Meaning |
|---|---|
| `say` | The narration of the step |
| `do` | A list of actions |
| `chapter` | A title card |
| `note` | A caption box on screen for the length of the step |
| `pause` | Extra seconds to hold at the end |

| Action | Form |
|---|---|
| `click`, `hover`, `scroll_to`, `wait_for` | `click: {role: button, name: Save}` |
| `fill` | `fill: {label: Email, value: sam@example.com}` |
| `select` | `select: {label: Role, option: Admin}` |
| `press` | `press: Enter` or `press: Control+K` |
| `goto` | `goto: https://app.example.com/settings` |

A locator names exactly one element. Use the first form in this list that identifies it:

1. `role` with `name`: `{role: button, name: Save}`
2. `label`: `{label: Email address}`
3. `placeholder`: `{placeholder: name@example.com}`
4. `text`: `{text: Welcome back}`
5. `testid`: `{testid: save-button}`
6. `css`: `{css: "form > button"}`. The last resort, because it breaks when the page's markup changes.

Three more keys narrow a locator: `exact: true`, `nth: 0` (the first of several) and `within: {role: dialog}`.

## Narration

- Address the viewer as "you", in the present tense.
- One or two short sentences per step. Each sentence becomes one subtitle.
- Say what to do and why it matters: "Open Settings, where teammates are managed."
- Name each control exactly as the screen names it.
- Write for the ear: no URLs, no symbols, and numbers as you would say them.
- A sentence ends at a full stop, a question mark or an exclamation mark followed by a space. To keep an abbreviation such as "e.g." inside a sentence, write `say` as a list with one sentence per item.

`howto narrate FILE` speaks the narration without a browser and writes a WAV file. Use it when the user wants to hear the wording before a take.

## Rules

- Never put a real password, token or personal address in a storyboard. A typed value is demo data.
- Do not guess a locator. Probe, read the outline, then write.
- When `setup` fails on a storyboard that has a profile, the session is probably signed out. Ask the user to run `howto login NAME URL`.
- When a render fails, fix the storyboard and render again. An earlier video is never replaced by a failed run.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | A step, the narration or the assembly failed |
| 2 | The storyboard or the command line is wrong. The message names the step and the field |
