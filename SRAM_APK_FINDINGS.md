# SRAM AXS APK findings

Analysis date: 2026-09-26. Input supplied by the user: SRAM AXS 2.52.0,
build 210022002, package `com.sram.armyknife`.
APK SHA-256: `d778ec4cbbda9ee5f77570bff31581cb21035a440802744316c47da75e78d351`.

## Method and evidence

Static analysis only; the APK was not installed or executed. Assets and the
x86_64 native libraries were extracted under ignored `data/apk-analysis/`.
JADX 1.5.6 was used for Java/Kotlin decompilation. `nm` and `objdump` expose
named native functions in `libsramsdkcpp.so`. Direct constant-returning
`getServiceCharacteristic()` functions provide the mappings below. ELF virtual
addresses were translated through PT_LOAD segments before reading UUID bytes.
The extracted 149 getter mappings are in `data/apk-analysis/native-uuid-map.json`;
the complete disassembly is retained alongside it. Mappings with indirect or
computed getters are not covered by that extraction.
JADX completed with 413 decompilation errors; Java output is partial. The UUID
findings below come from native disassembly and do not depend on those failures.

## Confirmed app mappings

UUID short forms use `d905XXXX-90aa-4c7c-b036-1e01fb8eb7ee`.

| Characteristic | Native coder | Observation on this Force |
|---|---|---|
| 0009 | DrivetrainStatus0Coder | Absent in captured GATT trees |
| 000b | DrivetrainStatus1Coder | Absent in captured GATT trees |
| 000a | DrivetrainConfigCoder | Absent in captured GATT trees |
| 0006 | EnhancedModeCoder | Present, decrypted |
| 0008 | SpdConfigCoder | Present, decrypted; acronym not interpreted here |
| 0011 | FdReactionConfigCoder | Present, decrypted |
| 0021 | Rd0ReactionConfigCoder | Present, decrypted |
| 0022 | Rd1ReactionConfigCoder | Present, decrypted |
| 0024 | MultishiftConfigInCoder | Present, decrypted |
| 0025 | MultishiftConfigOutCoder | Present, decrypted |
| 0003 | SramDynamicStatusCoder | Present, plaintext component records |
| 0002 | SramStaticVersionsCoder | Present, plaintext component records |
| fe57 | SramEnterDfuCoder | Read previously returned AA; never write for telemetry |

Both direct drivetrain status variants use service 0005. Their getter addresses
are `0x43dc10` (Status0) and `0x43da40` (Status1). The wrapper also has a
synthetic-looking UUID `575ff089-e98d-4a2d-a62f-c3743e55674e`; this is not evidence
that the physical peripheral exposes another GATT characteristic.

This identifies the seven decrypted channels as configuration, explaining their
unchanged values across shifts. Applying a GX decoder to protobuf field numbers
without respecting message identity would mislabel settings as gear positions.
In this APK, 0025 is multishift configuration, not cassette tooth counts.

The Java model `com.sram.axsplatform.models.DrivetrainStatus` contains
`fd_position`, `rd_position`, and `rd_trim`. This confirms the app's vocabulary,
not that every Force firmware exposes these values.

## Remaining lead

The native SDK also contains a DASH request transport, including
`SramDeviceIOImpl::gadget_read_op`, `setup_dash_service`, `get_data_capabilities`,
and `DashServiceImpl::query_sids`. Support on this Force and the exact transport
selection/UUIDs have not been established. The presence of these functions in
the app does not justify sending guessed commands to the bike.

Further tracing of `setup_dash_service` at `0x2cd700` shows a protocol-value
check against 2 and references to UUIDs `adee0001` / `adee0003` with bases
`-7726-453c-a069-007ea97a0add` and `-7727-453c-a069-007ea97a0add`.
Neither family appears in the captured Force GATT tree. Thus DASH is a real
alternate app transport, but there is no observed endpoint for it on this bike.

`assets/devices.yml` is explicitly mock-device configuration. Its status values
are simulated and are not evidence of Force hardware capabilities.

No live gear decoder has been established. Next work is to trace transport
selection and capability checks, then compare requirements with the captured
Force GATT tree. No firmware update or configuration write was performed.

## BlueZ cache check, 20:34 UTC

Before reconnecting, `bluetoothctl info` reported the SRAM device unavailable.
The only device file under `/var/lib/bluetooth` was a cache file containing
`[General]` and its name, with no GATT attributes. That file was moved to a private
backup, then the device was rediscovered and connected. All 19 characteristics
matched the previous set; 0009 and 000b remained absent. The existing SRAMBond
key still authenticated seven characteristics. Evidence is in
`data/rpi/sram-bond-probe-20260926T203430Z.json` and `sram-cache-check.json`.
There is no evidence that a stale on-disk GATT cache explains the missing channels.

## Capability and session control-flow audit

The follow-up inspected these native SDK paths:

- `DrivetrainStatusCoder::getCapabilities` (`0x40eed0`) delegates to the
  Status1 child when present, otherwise Status0; when neither exists it returns
  zero capability bytes. Its `read` implementation (`0x40e630`) similarly
  delegates through these child coders. No model ID, minimum firmware version,
  or bond creation call was found in these wrapper paths.
- `Coder::getCapabilities` (`0x3d55b0`) obtains the coder's service/characteristic
  pair and asks the peripheral for capabilities. It does not synthesize a
  position endpoint from configuration data.
- `GadgetImpl::add_uuids` (`0x4a9930`) builds the service/characteristic inventory
  and calls `allCodersFromSrvChars` (`0x3d6de0`). Logical wrappers may be included
  in that inventory; their presence is not proof of a physical characteristic.
- `SramDeviceIOImpl::gadget_capabilities_op` (`0x2d4fc0`) takes the DASH path
  only when the active protocol equals 2, a DASH service object exists, and the
  mapped SID is supported; otherwise it queries actual BLE capabilities.
- The Java `ProtocolVersion` enum explicitly maps `SL_DYN=0`, `PARALLEL=1`,
  `DASH=2`, `UNKNOWN=-1`, `ERROR=-2`, and `NOT_REQUIRED=255`.

The inspected capability/read paths yielded no activation command or reason to
repeat SRAMBond. Successful authentication of seven settings establishes that
our key works for those settings, not that every possible session requirement
has been excluded. Firmware support for other versions remains unproven.

Evidence is saved in `data/apk-analysis/capability-control-flow.asm` and
`force-capability-audit.json`. These findings support the narrower conclusion:
the app's identified position readers have no matching endpoint in our fresh
Force GATT capture. They do not prove that no undocumented mode could exist.
The next independent check would be the official app connected to this exact
Force: verify whether it can display live position, and, if so, capture its BLE
interaction. Further blind gear sweeps do not address the missing endpoint.
