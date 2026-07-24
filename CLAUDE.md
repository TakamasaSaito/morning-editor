# CLAUDE.md

プロジェクト管理方針は TakamasaSaito/portfolio-dashboard/POLICY.md を参照(gh api で取得可)。

## VOICEVOX 疎通しない時の切り分け手順

`src/audio.py` は localhost 失敗時にゲートウェイIPへ自動フォールバックするが、
それでも繋がらない場合は以下の順で切り分ける。

### 1. WSL側でポート待受確認 (netstat)

```bash
netstat -an | grep 50021
```

何も表示されなければ Windows側の VOICEVOX Engine が起動していない。

### 2. Windows側の portproxy 設定確認

管理者 PowerShell で確認:

```powershell
netsh interface portproxy show all
```

`0.0.0.0:50021` → `127.0.0.1:50021` のエントリが存在すること。
ない場合は手順3で追加する。

### 3. portproxy の追加 (管理者 PowerShell)

```powershell
netsh interface portproxy add v4tov4 listenport=50021 listenaddress=0.0.0.0 connectport=50021 connectaddress=127.0.0.1
```

追加後、WSL から `curl http://<ゲートウェイIP>:50021/version` で疎通を確認する。
ゲートウェイIPは `ip route show default` の `via` フィールドで確認できる。
