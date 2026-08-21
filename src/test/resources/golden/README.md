# Golden SQL and AST snapshots

The `.sql` and `.json` files in this directory are reviewed compiler outputs.
Normal test runs compare generated output with these files and report the first
changed line. Tests never update snapshots by default.

When an intentional compiler rule or AST schema change affects the output:

1. Describe the semantic reason for the change in the commit or pull request.
2. Regenerate snapshots with
   `mvn -DupdateGolden=true -Dtest=GoldenSnapshotTest test`.
3. Review every SQL and JSON diff before committing it.
4. Increment `AstSnapshot.SCHEMA_VERSION` for an incompatible AST snapshot
   shape change.
