# Forge machine identity: the hapax-forge GitHub App (operator act O2)

Estate commits and pull requests should come from a machine identity, not the operator's
personal account. Before this, 36 of 38 PRs were authored by the personal account. The
identity is an **org-owned GitHub App** on `hapax-systems`. Only the forge-send service holds
its private key. It mints a one-hour installation token per send, narrowed to one repository,
and GitHub attributes the resulting commits to the App's bot, `hapax-forge[bot]`.

Design: `30-areas/hapax/frame/communication-pathway-20260925/O2-FORGE-MACHINE-IDENTITY-DESIGN-20260925.md`
(vault). Code: `shared/forge_app_identity.py`, `scripts/hapax-forge-app-setup`,
`systemd/units/hapax-forge-send.service`.

## What this does and does not guarantee

- The key is readable only by the forge-send unit's dynamic user and by root. systemd delivers
  it with `LoadCredentialEncrypted=forge-app-key`, "only accessible to the user associated with
  the unit … as well as the superuser" (`man systemd.exec`).
- Lanes run as the operator's uid 1000 and cannot read it. Against a lane that escalates, this
  is class (b) until O5 removes passwordless sudo.
- It does not revoke the personal `gh` token, and it does not change the personal profile. Both
  are the operator's own acts.

## Ruling recorded: the FileStore holds no key

Seat, 2026-09-25T07:48:10Z (`lanebus/dev27/20260925T0748Z-dev1-o2-rulings.md`): the private
key goes straight from the manifest conversion into `systemd-creds` and the root credstore. The
FileStore (`hapax-secret`) holds **non-secret metadata only**: app id, client id, slug, owner,
bot user id, under `forge-app/identity`. The FileStore is lane-readable, so a key stored there
would be readable by every lane.

## Operator steps

Step 1 needs the operator's browser identity. It waits for the hostile-reader panel to pass the
App's public text (tier A, O1): the name, description and homepage in
`forge-machine-identity-app-manifest.json`. The panel (dev20, 2026-09-25T08:28:42Z) passed its own
replacement description, which the manifest carries verbatim; a test pins it, because any change
needs a new panel pass. The seat confirms that the verdict meets tier A's "nothing new" rule.

The redirect goes to the org page by design. The operator copies `code` from the address bar, so
the key is fetched only by step 2's process and never passes through a web server.

1. **Create the App (browser, one click).**
   ```
   scripts/hapax-forge-app-setup form /store-fast/tmp/hapax-forge-form.html
   ```
   Open that file in a browser signed in as an owner of `hapax-systems`, and click **Create GitHub
   App**. GitHub shows the creation page for the org. Confirm it. GitHub then redirects to
   `https://github.com/hapax-systems?code=…&state=…`. Copy `code` and `state` from the address
   bar. The code expires in **one hour**.

2. **Move the key into the credstore (terminal, as the operator; sudo is used for one write).**
   ```
   scripts/hapax-forge-app-setup convert <code> <state> --state-file /store-fast/tmp/hapax-forge-form.html.state
   ```
   It refuses, writing nothing, when:
   - the state does not match;
   - the App is not owned by `hapax-systems`;
   - the response has no key;
   - `/etc/credstore.encrypted/forge-app-key` already exists and `--replace` was not given.

   It prints the non-secret identity. Then delete the two files it read, the form and the state
   file.

3. **Install the App (browser).** In the App's settings, click Install, choose **Only select
   repositories**, and select **hapax-council**. Add more repositories only as forge-send starts
   serving them; each addition is a deliberate act.

## Rotation and revocation

- **Rotate** (for example after an exposure, which falls under O9's bounded exemption):
  1. Generate a new key in the App's settings.
  2. Pipe it with `--replace` into the same credstore target.
  3. Delete the old key in the App's settings.
  4. The old key stops working when it is deleted at GitHub, not before.
- **Revoke:**
  1. Delete the key, or the App, in the App's settings.
  2. `sudo rm /etc/credstore.encrypted/forge-app-key`.

## Not yet built (O2 PR 2)

- The forge-send entry point and its root installer. These land with the request intake:
  read-once, a create-only spool, and the R7 record check composed before any network call.
- The runtime leg: one PR opened by `hapax-forge[bot]` on a test branch, observed in the GitHub
  UI and API.
- A provenance trailer on every commit forge-send sends, naming the model and harness that wrote
  the change (panel finding F6). The App is private, so only installers see its description;
  readers meet the bot's commits, so the provenance must travel with them.
