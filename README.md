# Bike Safety Computer

Prototipo di ciclocomputer su **Raspberry Pi 5**, con raccolta BLE in Python,
log JSONL, dashboard terminale e pagina web Flask accessibile dal PC.

## Stato attuale

| Componente | Funzioni implementate |
| --- | --- |
| COOSPO H808S | Battiti, contatto, intervalli RR quando presenti, batteria |
| Trek DuoTrap S | Velocità, cadenza, contatori ruota/pedivella, batteria |
| Trek Ion Pro RT / Flare RT | Lettura modalità e batteria; comandi on/off/flash tramite script dedicato |
| SRAM Force AXS 2×12 | Quattro tensioni batteria sperimentali, identificativi e contatori; marcia non decodificata |
| Dashboard Flask | Pagina live sulla porta **5050**, sezioni per sensore, colori e stato connessioni |
| Registrazione | Un file JSONL per sessione, condiviso fra tutti i sensori |

Il trasporto implementato oggi è **BLE**. ANT+ è una possibile estensione,
prima per le marce SRAM e poi per altri sensori, mantenendo eventualmente
entrambi i protocolli. Non è ancora implementato un ricevitore ANT+.

La configurazione attuale è specifica della bici usata per lo sviluppo:
indirizzi BLE in `bike_telemetry.py`, corone **35/48** e cassetta
**10-11-12-13-14-15-17-19-21-24-28-33** documentate in `drivetrain.json`.
La velocità assume una circonferenza di **2.136 m**: va calibrata sulla ruota.

## Obiettivo e sviluppi futuri

L'obiettivo è un dispositivo da manubrio con schermo monocromatico robusto,
pulsanti fisici e pagine configurabili. GPS, sensori ambientali, telecamere,
radar e misuratore di potenza sono possibili estensioni; non fanno parte della
raccolta attuale. Il progetto di analisi delle condizioni stradali e della
sicurezza rimane una direzione di ricerca, non una funzione implementata.

Per SRAM si attende un eventuale supporto Force nel progetto
[GaborWnuk/sram-axs](https://github.com/GaborWnuk/sram-axs); l'alternativa prevista
è aggiungere un dongle ANT+ e il relativo profilo. Nessuna marcia viene stimata
dal rapporto fra velocità e cadenza. I risultati dell'indagine BLE sono raccolti
in [SRAM_APK_FINDINGS.md](SRAM_APK_FINDINGS.md).

## Dashboard web Flask

Dal PC apri **http://rpi5-00.local:5050** sulla stessa rete del Raspberry.
La pagina si aggiorna ogni mezzo secondo: cardio, velocità, cadenza,
modalità/batterie delle luci e dati SRAM, con età delle letture e colori.
Un solo raccoglitore serve tutti i browser e registra anche a pagina chiusa.
I campi non trasmessi, non supportati o non disponibili sono nascosti sia sul
web sia nel terminale; errori e stato connessione restano visibili. I log
conservano anche le informazioni sui dati mancanti.
Le letture precedenti disponibili rimangono visibili con la loro età; se il collegamento
web si interrompe, gli indicatori principali diventano indisponibili.

```bash
./scripts/rpi.sh deploy
./scripts/rpi.sh start       # Server web e raccolta BLE, continua dopo logout
./scripts/rpi.sh status
./scripts/rpi.sh stop
```

Avvio manuale sul Pi (con il servizio fermo):

```bash
~/pyenv/bin/python ~/bike-safety-computer/web_server.py
```

Opzioni: `--port 5050`, `--host 0.0.0.0`, `--wheel-circumference 2.136`,
`--sram-interval 0.5`, `--poll-interval 10`, `--log PERCORSO`.
Il server Flask usa un singolo processo con server Werkzeug threaded, senza
reloader/debug, per l'uso sulla rete locale. La pagina è di sola lettura e
non richiede risorse esterne. Non c'è autenticazione: chi può raggiungere la
porta sulla rete può leggere la telemetria. `/api/state` espone lo stesso
stato in JSON; nessuna richiesta HTTP avvia nuove connessioni ai sensori.
Log misure in `data/telemetry-*.jsonl`, diagnostica in `data/web-*.log`.

**La dashboard terminale e il server web sono alternative:** condividono il
lock `.telemetry.lock`; ferma il servizio prima di usare `dashboard.py`.

## Telemetria BLE live

`bike_telemetry.py` è la libreria di raccolta; `dashboard.py` mostra i dati in
terminale e registra automaticamente **tutti i sensori** in un unico JSONL.
Il vecchio servizio dedicato al cardio viene rimosso durante il deploy;
le registrazioni precedenti vengono conservate.

Dal PC:

```bash
./scripts/rpi.sh deploy
./scripts/rpi.sh stop        # Se la raccolta web è attiva
./scripts/rpi.sh dashboard
```

Direttamente sul Raspberry:

```bash
~/pyenv/bin/python ~/bike-safety-computer/dashboard.py
```

Indossa la fascia, gira ruota/pedali e sveglia i dispositivi da leggere.
Le sezioni mostrano cardio (bpm, contatto, RR, energia se trasmessa, batteria),
DuoTrap (velocità, cadenza, contatori, batteria), le due luci (modalità e batteria)
e SRAM (quattro tensioni sperimentali, seriali, stato e contatori).
La marcia SRAM non è decodificata: la relativa riga non disponibile è nascosta.
Gli indirizzi dei dispositivi di questa bici sono in `bike_telemetry.DEVICES`.

- Titoli ciano, velocità/cadenza verdi, valori appena cambiati gialli per 2 secondi.
- Frecce o PgUp/PgDn per scorrere; `q` o Ctrl+C per uscire.
- Ogni lettura riporta la propria età: un valore vecchio non è una nuova misura.
- Cardio e DuoTrap ricevono notifiche. SRAM mantiene una connessione aperta,
  indipendente dalle luci, con una pausa di 0.5 s dopo ogni lettura
  (`--sram-interval`). La durata della richiesta si aggiunge alla pausa;
  lo schermo mostra anche l'intervallo effettivo e la durata delle letture.
  Questo non garantisce che il firmware aggiorni il contenuto a ogni richiesta.
- Le luci vengono lette a turno, con una pausa di 10 secondi fra i cicli
  (più il tempo di connessione/lettura). Sono possibili fino a quattro
  connessioni contemporanee: cardio, DuoTrap, SRAM e una luce.
- Ogni connessione usa una nuova ricerca BLE, con ricerca e connessione
  serializzate. La prima enumerazione dei servizi può richiedere decine di
  secondi per sensore: il limite è 90 s, e lo schermo distingue questa fase
  dall'attesa dell'adattatore. Gli errori completi sono in `data/diagnostics-*.log`.
- La velocità usa una circonferenza **ipotizzata** di 2.136 m per 700x28C;
  correggila con `--wheel-circumference METRI`. Zero dopo 5 s senza impulsi
  è una convenzione di inattività. In assenza di dati recenti appare `--`.
- `--raw` mostra anche gli esadecimali; `--plain` stampa istantanee senza colori.
- `--log PERCORSO` sceglie il file; altrimenti ogni avvio crea
  `~/bike-safety-computer/data/telemetry-DATA.jsonl`.

Il JSONL contiene timestamp UTC, tempo monotono, dispositivo, indirizzo,
valori visualizzati, dati numerici decodificati e payload originali delle letture.
Le tensioni SRAM non vengono convertite in percentuali. Il log cresce fino
all'uscita, senza rotazione automatica. Gli annunci radio servono alla scoperta;
il file registra le misure GATT acquisite, non una cattura di tutto il traffico BLE.

### Uso come libreria

```python
import asyncio
from bike_telemetry import BikeTelemetry, TelemetryConfig

async def main():
    telemetry = BikeTelemetry(TelemetryConfig(), on_event=lambda event: print(event))
    # telemetry.sections espone i valori correnti; telemetry.stop.set() termina.
    await telemetry.run()

asyncio.run(main())
```

La callback è sincrona: deve essere breve e non bloccare il loop asyncio.
La libreria raccoglie e registra senza dipendere dall'interfaccia terminale.

### Servizio facoltativo e deploy

Il deploy usa SSH verso `rpi5-00.local`, crea `~/bike-safety-computer` e usa
`~/pyenv`. Richiede Python 3.10+, BlueZ e Bluetooth attivo. Per cambiare host:
`RPI_HOST=fra@rpi5-00.local ./scripts/rpi.sh deploy`.
Installa `bike-telemetry.service`, **senza avviarlo o abilitarlo automaticamente**.
Dopo un aggiornamento usa `./scripts/rpi.sh restart` per caricare il nuovo codice.

```bash
./scripts/rpi.sh start       # Raccolta e dashboard web
./scripts/rpi.sh status
./scripts/rpi.sh stop        # Fermalo prima di aprire la dashboard
./scripts/rpi.sh enable      # Avvio al boot; richiede sudo per linger
./scripts/rpi.sh disable
./scripts/rpi.sh fetch       # Copia i log sul PC in data/rpi
```

Servizio e dashboard registrano nello stesso formato. Un lock impedisce due
istanze del programma contemporanee. Non avviare altri strumenti BLE sugli
stessi sensori durante la raccolta. `disable` conserva il linger utente per
non interferire con altri servizi.

## Trek lights over BLE

The `lights.py` utility discovers Ion Pro RT and Flare RT by their advertised
names, reads the battery and mode table, and supports a steady low mode or off.
Stop `bike-telemetry.service` before using these standalone commands, then
restart it afterwards. The script verifies the mode label before writing and
reads the mode back afterwards.
With multiple lights of the same name, discovery selects the first match.

```bash
./scripts/rpi.sh deploy
./scripts/rpi.sh lights status
./scripts/rpi.sh lights on                  # Both: mode 5 (low/night steady)
./scripts/rpi.sh lights off
./scripts/rpi.sh lights flash               # Both: Day Flash, using each light's mode table
./scripts/rpi.sh lights on --light front    # Or rear
```

The mode characteristic was identified using
[independent Ion 200 RT protocol research](https://gist.github.com/mywalkb/e0de3828cc0a84860a07bde5a6ec6c5c).
The script checks the connected light's own mode descriptions rather than
assuming all models have the same modes. Readback confirms the reported mode;
visual confirmation of the LEDs remains separate.

## SRAM AXS inspection

The user-confirmed Force AXS 2x12 gearing is saved in `drivetrain.json`:
cassette 10-11-12-13-14-15-17-19-21-24-28-33 and chainrings 35/48.
Arrays are ordered by increasing tooth count. BLE position numbering and its
mapping to these arrays remain unknown; array indices are not device positions.

```bash
./scripts/rpi.sh sram scan
./scripts/rpi.sh sram probe --seconds 30
./scripts/rpi.sh sram probe --address AA:BB:CC:DD:EE:FF
./scripts/rpi.sh sram capture --address AA:BB:CC:DD:EE:FF --seconds 40
./scripts/rpi.sh fetch
```

Wake the rear derailleur and disconnect the SRAM phone app before discovery.
`probe` records the GATT service tree and selected readable identification,
battery and telemetry characteristics in `data/sram-*.json` on the Pi.
It does not write, pair, or change drivetrain settings. Vendor payloads remain
raw until their interpretation is verified on this Force AXS; the upstream
protocol research was validated on a GX Eagle Transmission. Live gear decoding
is not implemented yet.

`capture` repeatedly reads selected telemetry characteristics into a JSONL file.
It announces a ten-second baseline followed by a shift phase. Record the actual
starting gear and each manual shift separately; changing bytes alone do not
establish a gear decoder. The connected drivetrain is a Force AXS **2x12**.

### Experimental SRAMBond

`sram_bond.py` adapts the MPL-2.0 SRAMBond implementation from
[Gabor Wnuk's sram-axs](https://github.com/GaborWnuk/sram-axs).
Its DH/EAX calculations were checked against a published known-answer vector,
including rejection of a modified authentication tag. Force compatibility and
gear decoding are still under investigation.

Close the SRAM app and put the rear derailleur in AXS pairing mode first.
Creating a bond renews the diagnostics key; the upstream project reports that
the official app re-bonds on a subsequent connection. Existing shifting uses a
separate link. Only the SRAMBond characteristic is written by this tool.

```bash
./scripts/rpi.sh sram_bond bond --address AA:BB:CC:DD:EE:FF --ready
./scripts/rpi.sh sram_bond read --address AA:BB:CC:DD:EE:FF
./scripts/rpi.sh sram_bond read --address AA:BB:CC:DD:EE:FF --all-readable --gear-label 48x11
```

`--all-readable` also reads remaining readable characteristics, excluding bond
and token endpoints. `--gear-label` records a user-supplied reference, not a
decoded position. The extended Force probe on 2026-09-26 returned `aa` from
`d905fe57` and seven zero bytes from `d905fe53`; their meanings remain unknown.

Keys are saved with restricted permissions under `.secrets/` on the Pi, excluded
from Git and `fetch`. A saved key prevents accidental repeat bonding. Probe
results are written under `data/`; successful authenticated decryption alone
does not establish that a field is gear position.

Force 2x12 bench result (2026-09-26): **SRAMBond pairing succeeded** after the
rider held the rear derailleur AXS button until the LED blinked. The exchange
returned a 16-byte public key and a 48-byte authenticated key blob fragmented
as 20+20+8 bytes. The key was saved on the Pi and FINALIZE was acknowledged.
Authenticated decryption succeeded for `d9050024`, `d9050025`, `d9050008`,
and `d9050006`. Field meanings and live gear decoding remain unverified.

Earlier attempts returned 48-byte responses to both writes. The rider later
clarified they had only briefly pressed the button; those failures did not
establish protocol incompatibility. The diagnostic is retained as
`data/sram-handshake-diagnostic.json` (also fetched to the PC).

### SRAM battery advertisements

```bash
./scripts/rpi.sh sram_batteries --seconds 45
./scripts/rpi.sh fetch
```

Briefly press each component's AXS button while the scan is running. The tool
records advertisements without connecting. It recognizes the battery record
documented by esphome-sram-axs; decoded values remain candidates until checked
on this hardware. The Force advertisement observed so far contains an 11-byte
FE51 service record and no manufacturer battery record, so it has not yielded
a verified battery percentage. Missing advertisements do not mean a flat battery.

Saved Force GATT probes can also be inspected locally:

```bash
python3 sram_records.py data/rpi/sram-bond-probe-20260926T195620Z.json --output data/rpi/sram-battery-records.json
```

The observed `d9050003` payload has a 6-byte header followed by five 24-byte
records. Serial numbers match the rear derailleur and the second advertised
component. Four nonzero product records contain an unsigned little-endian field
at record offset 8: 7861, 2890, 2950 and 7915–7916 in this snapshot. Interpreting
these as millivolts is a hypothesis, not a validated battery decoder. Status 3
is also uninterpreted. No percentages or charge classifications are derived.
One additional product-zero record repeats the rear serial and is retained raw.

Battery swap experiment (2026-09-26, 20:07 UTC): after the rider swapped the two
derailleur packs, product 1003's candidate field increased from 7861 to 7978;
the rear product 1001 decreased from 7915–7916 to 7796, then 7792 on a second
read. The ordering reversed, supporting battery dependence but not establishing
millivolt scaling or a charge percentage. The baseline was about 11 minutes
earlier and the values did not swap exactly. Controller product 1006 reported
2818; product 1007 changed to status 128 with a zero field, treated as unavailable
rather than an empty battery. Captures and the comparison remain under `data/rpi/`.
