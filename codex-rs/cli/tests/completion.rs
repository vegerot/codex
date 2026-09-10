//! Exercises generated completions through Zsh's line editor in a real terminal.

#![cfg(unix)]

use std::collections::HashMap;
use std::time::Duration;

use anyhow::Context as _;
use codex_utils_pty::SpawnedProcess;
use codex_utils_pty::TerminalSize;
use codex_utils_pty::spawn_pty_process;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

#[tokio::test]
async fn zsh_completes_nested_subcommands() -> anyhow::Result<()> {
    let Ok(zsh) = which::which("zsh") else {
        eprintln!("skipping Zsh completion test: zsh is not installed");
        return Ok(());
    };
    let temp_dir = TempDir::new()?;
    let completion_path = temp_dir.path().join("_codex");
    let completion = assert_cmd::Command::new(codex_utils_cargo_bin::cargo_bin("codex")?)
        .env("CODEX_HOME", temp_dir.path())
        .args(["completion", "zsh"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    std::fs::write(&completion_path, completion)?;

    let mut env: HashMap<String, String> = std::env::vars().collect();
    env.insert("TERM".to_string(), "xterm-256color".to_string());
    env.insert(
        "CODEX_COMPLETION_SCRIPT".to_string(),
        completion_path.to_string_lossy().into_owned(),
    );
    let SpawnedProcess {
        session,
        mut stdout_rx,
        exit_rx,
        ..
    } = spawn_pty_process(
        &zsh.to_string_lossy(),
        &["-f".to_string()],
        temp_dir.path(),
        &env,
        /*arg0*/ &None,
        TerminalSize::default(),
        &[],
    )
    .await?;

    // Invoke the actual Tab completion widget without executing the completed
    // commands. Only the final `exit` is submitted to the shell.
    let script = r#"
unset HISTFILE
unsetopt beep
PROMPT=''
RPROMPT=''
autoload -Uz compinit
compinit -D
source "$CODEX_COMPLETION_SCRIPT"
_completion_test() {
    local input
    for input in 'codex remote-control pa' 'codex --model example remote-control pa' 'codex mcp li' 'codex app-server daemon sta' 'codex --ver'; do
        BUFFER=$input
        CURSOR=${#BUFFER}
        zle complete-word
        print
        print -r -- "COMPLETED:$BUFFER"
    done
    BUFFER=exit
    zle .accept-line
}
zle -N zle-line-init _completion_test
"#;
    session
        .writer_sender()
        .send(script.as_bytes().to_vec())
        .await?;
    let mut output = Vec::new();
    let code = tokio::time::timeout(Duration::from_secs(30), async {
        while let Some(bytes) = stdout_rx.recv().await {
            output.extend_from_slice(&bytes);
        }
        exit_rx.await
    })
    .await
    .context("Zsh completion timed out")??;
    let output = String::from_utf8_lossy(&output).replace('\r', "");
    assert_eq!(code, 0, "Zsh completion failed: {output}");
    let completed: Vec<_> = output
        .lines()
        .filter_map(|line| line.strip_prefix("COMPLETED:"))
        .collect();
    insta::assert_debug_snapshot!(completed, @r#"
    [
        "codex remote-control pair ",
        "codex --model example remote-control pair ",
        "codex mcp list ",
        "codex app-server daemon start ",
        "codex --version ",
    ]
    "#);
    Ok(())
}
