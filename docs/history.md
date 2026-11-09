# Server configuration history

`basic/history` registers a non-sidebar service through the shared registry.
The configuration store binds that optional service and the log service. The
existing Version history toolbar button becomes available for saved server
configurations. Removing the history package before startup leaves configuration
editing usable and disables that button.

Each version is a UTF-8 `.version.json` file under:

```
conf/.history/<SHA-256 of resource identity>/<timestamp>_<uuid>.version.json
```

The JSON envelope includes schema version, resource identity, version identifier,
recording time, action and complete configuration content. The current server
file remains `.server.json`; its field format is unchanged. Snapshots include
the authentication information required to restore the complete configuration.
The history preview masks PASSWORD values, and ordinary operation logs contain
only metadata and field names.

New and copied configurations create initial versions. Saving captures the
existing file before atomic replacement and the new file afterwards. Consecutive
identical content is deduplicated. Renaming carries the old history to the new
identity; an existing archive is merged without discarding the source archive.
Deleting a configuration keeps its last snapshot and history. Archives are
grouped by configuration name; reusing a deleted name also makes its prior
versions available under that identity.

Open Version history to select and preview a version, restore it, or delete a
version. Unsaved edits are handled with the existing Save/Discard/Cancel prompt
before opening history. Restoring asks for confirmation, validates the selected
configuration, preserves the current file as a snapshot, then saves and reloads
the chosen configuration. Existing SSH connections continue during a file
restore. A later connection uses the restored saved data.

If preserving the current file's history fails, replacement/deletion is aborted.
If the new snapshot fails after an actual configuration change, the completed
change remains saved and the UI reports the history failure. Snapshot files use
temporary files followed by replacement; identifiers and paths are constrained
to the configured history root. History creation/deletion and configuration
restoration also produce operation logs.

No periodic capture of unsaved drafts, automatic pruning, old `.txt` migration,
application startup, build or tests were performed in this stage. All data files
are created only by user operations in the running application.
