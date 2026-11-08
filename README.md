# Test-SCOR-app

SCOR 11.0 Explorer, a student exercise for browsing the Supply Chain Operations Reference model by code.

- **Metrics** by performance attribute (Reliability, Responsiveness, Agility, Cost, Asset Management, GreenSCOR) and level, with their diagnostic decomposition
- **Processes** (Plan, Source, Make, Deliver, Return, Enable) at levels 1 to 3
- **Practices** (Emerging, Best, Standard) and **People** skills, experiences, trainings and aptitudes
- Cross-links between all of them, plus the page in the SCOR 11.0 PDF where each element is described

Only codes, titles and relationships are included (`data/scor.json`, about 1,400 elements and 6,000 links).
SCOR definitions and body text are not reproduced. SCOR is © Supply Chain Council.

## Running

The app runs on Railway: `npm run build` builds the React frontend with Vite, and `npm start` starts the
Express server. On startup the server creates its tables in the Railway PostgreSQL database (`DATABASE_URL`)
and loads `data/scor.json` whenever the file has changed.

`tools/pdf/` has the one-off scripts that produced `data/scor.json` from the PDF.
