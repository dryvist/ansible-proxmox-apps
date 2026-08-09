# Modeling Physical Hardware in Nautobot

Which DCIM model to use for a piece of physical hardware, and why the choice is
not obvious. Written because the wrong answer here looks correct right up until
you try to record a component that is not installed in anything.

Applies to Nautobot 2.3.0 and later. See [Version prerequisite](#version-prerequisite).

## The three models

| Model | Represents | Requires |
| --- | --- | --- |
| `Device` | A whole chassis — something with its own control plane | A `DeviceType` and a `Location` |
| `Module` | A component installable in a device or another module | A `ModuleType`, and either a parent `ModuleBay` **or** a `Location` |
| `InventoryItem` | A component that is neither a `Module` nor another device component | A parent `Device` — **always** |

`InventoryItem` exists for hardware that cannot be modeled any other way. It
cannot be templatized on a device type and cannot be cabled; it serves inventory
purposes only. Since 2.3.0, line cards and similar hardware that depends on the
parent's control plane should be a `Module` instead.

## Spare and uninstalled parts

**A component that is not installed in anything is a `Module` with a
`location`.** From the Nautobot documentation on the Module model:

> For modules existing as spares, the `location` field can be used instead of
> `parent_module_bay`, but not simultaneously. A `location` can only be set if
> the module is not in a module bay; otherwise, its location is inherited from
> the parent module bay.

So `parent_module_bay` and `location` are mutually exclusive, and the pair is
what makes a parts bin representable:

- **Installed** → `parent_module_bay` set, `location` null (inherited).
- **Spare / on a shelf / unassigned** → `location` set, `parent_module_bay` null.

Moving a part between those states is a field change on the same object, so a
component keeps its identity, serial and asset tag as it moves in and out of
service.

### The trap

Reaching for `InventoryItem` first is the natural move — the name matches the
intent, and it accepts a manufacturer, part ID, serial number and asset tag,
which is exactly the field set an asset record wants. But it requires a parent
`Device`, so it cannot represent anything sitting on a shelf.

Concluding from that "Nautobot cannot model spare parts" is wrong, and it leads
somewhere worse: inventing a synthetic placeholder device to act as a parts bin.
That puts a device in DCIM that does not exist, and every downstream consumer —
inventory, reporting, automation — has to know to filter it out. Use a `Module`
with a `location`; the model is already there.

## Consequences for a hardware import

- **Every component model needs a `ModuleType`**, under a manufacturer, in the
  same way every device needs a `DeviceType`. Ensure these before the sync,
  rather than creating them inline per row.
- **Installing a module needs a `ModuleBay` to install it into**, and bays are
  defined on the device/module type. Importing *installed* components therefore
  requires modeling bays on the relevant types first. Importing *spares* does
  not — a location is enough.
- **Deleting a module bay deletes the module installed in it.** Anything that
  reconciles bays must treat deletion as significant, not incidental.
- **Choose one model per class of component and keep it.** If installed parts
  are `InventoryItem`s and spares are `Module`s, the same physical part changes
  model class when it is pulled from a chassis, which breaks identity and any
  history attached to it.

## What does not belong in DCIM

Nautobot records what hardware *is* and where it *is*. It is a poor home for:

- Narrative — fault histories, compatibility findings, debugging write-ups.
  These belong in prose documentation, keyed by the same stable identifier used
  as the device/module name or asset tag, so the two can be joined by a reader.
- Procurement records where the hardware itself is not tracked. Purchase dates
  and prices are reasonable as custom fields on hardware Nautobot already
  models; they are not a reason to model hardware it otherwise would not.

A practical split: the structured columns of a hardware table become Nautobot
objects, and the free-text column stays in documentation. Absorbing the whole
table tends to destroy the free-text column, which is often where most of the
engineering value sits.

## Version prerequisite

`Module`, `ModuleType` and `ModuleBay` require **Nautobot 2.3.0+**. Before
designing an import around them, confirm the version actually running:

```sh
nautobot-server --version
```

**Do not infer the version from the installed package list.** An Ansible `pip`
task with `state: present` installs a package only when it is absent — it does
not upgrade one that is already there. A role that names `nautobot` with no
version pin therefore installs "latest stable" on the first converge and then
holds that version indefinitely, so a long-lived instance can be well behind the
current release while the role looks like it tracks it.

**Pin the version rather than reaching for `state: latest`.** Pinning fixes two
problems at once: pip reconciles to the named version instead of accepting any
installed one, and a dependency-update bot has something to compare and bump. An
unpinned dependency is invisible to that bot — there is no version to diff — so
"unpinned" does not mean "tracks upstream", it means "never moves and nothing
reports it". `state: latest` would upgrade, but it re-resolves on every run,
which costs idempotence and makes the deployed version a function of when the
converge happened rather than of anything in version control.

If the update bot uses annotation comments to find versions in files its built-in
managers do not parse, confirm the annotation actually matches before relying on
it — check the manager's file pattern and regex against the exact line being
added. An annotation with the wrong shape is silently inert, which looks
identical to a dependency that is simply up to date.

**Treat a major upgrade as a scheduled change.** Nautobot majors run database
migrations. A pin bump across a major should be applied deliberately, with a
backup taken first, not folded into a routine converge.

## References

- Module: <https://docs.nautobot.com/projects/core/en/stable/user-guide/core-data-model/dcim/module/>
- Module Bay: <https://docs.nautobot.com/projects/core/en/stable/user-guide/core-data-model/dcim/modulebay/>
- Inventory Item: <https://docs.nautobot.com/projects/core/en/stable/user-guide/core-data-model/dcim/inventoryitem/>
- Device Bay: <https://docs.nautobot.com/projects/core/en/stable/user-guide/core-data-model/dcim/devicebay/>
