
const mysql = require('mysql2/promise');
const fs = require('fs');
const app = fs.readFileSync('/app/app.js','utf8');
const m = app.match(/password:\s*process\.env\.DB_PASSWORD \|\| '([^']+)'/);
(async () => {
  try {
    const c = await mysql.createConnection({
      host: 'music-db', user: 'nubiapp', password: m ? m[1] : 'NONE',
      database: 'school_chat_db', port: 3306
    });
    const [r] = await c.execute('SELECT COUNT(*) n FROM students');
    console.log('DB_OK ' + JSON.stringify(r));
    await c.end();
  } catch (e) { console.log('DB_FAIL ' + e.message); }
})();
