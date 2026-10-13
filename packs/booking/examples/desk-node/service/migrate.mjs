// service/migrate.mjs — node service/migrate.mjs --db PATH: upgrade the journal a version 1 service left at PATH to
// version 2 in place (harness/SERVICE.md, "Upgrading from version 1"), with the shipped profile's migration: every
// resource gets buffer 0 and every booking, recorded result and event is kept. Running it again changes nothing; a
// journal it does not recognise is refused (non-zero exit) and left untouched.
import { migrate, Unrecognised } from "../profiles/node/store.mjs";

const at = process.argv.indexOf("--db");
if (at < 0 || !process.argv[at + 1]) { console.error("usage: node service/migrate.mjs --db PATH"); process.exit(2); }
try { console.log(migrate(process.argv[at + 1])); }
catch (e) {
  if (e instanceof Unrecognised) { console.error(`refused: ${e.message}`); process.exit(1); }
  throw e;
}
