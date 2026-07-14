# GitHub SSH workflow notes

This project uses SSH authentication for pushing to GitHub.

## Important Codex / sandbox note

When running inside Codex, access to the user's SSH configuration may be sandbox-restricted.
The SSH configuration file is expected to exist at:

```text
C:\Users\Yu Boyang\.ssh\config
```

The repository remote may use the SSH host alias:

```text
github.com-tensort
```

For example:

```text
git@github.com-tensort:Tensort-s/matsim-example-project.git
```

If a normal sandboxed command reports an error such as:

```text
ssh: Could not resolve hostname github.com-tensort
```

do not assume the SSH config is missing. In this project, the likely cause is that Codex was not allowed to read
`C:\Users\Yu Boyang\.ssh\config`.

In that situation, request elevated permission and rerun the Git/SSH command. The elevated command can read the SSH
config and use the configured key/alias correctly.

## Successful pattern

Use the project root:

```powershell
cd F:\Matsim\matsim-example-project
```

Then run Git push with elevated permission when using Codex tools:

```powershell
git push origin master
```

The successful remote observed for this project is:

```text
origin  git@github.com-tensort:Tensort-s/matsim-example-project.git
```

## Reminder for future sessions

For future Codex conversations:

- The SSH config is present under `C:\Users\Yu Boyang\.ssh\config`.
- `github.com-tensort` is a configured SSH host alias.
- If Codex cannot resolve the alias in sandboxed mode, ask the user for elevated permission instead of changing the
  remote or assuming the SSH setup is broken.
- After elevation, `git push origin master` has previously succeeded.
