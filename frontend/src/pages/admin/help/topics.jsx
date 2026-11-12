import PaperFormatLinks from "@/components/PaperFormatLinks"
import { Sample, SampleOf, SamplePack, TryCoding, TryExam, TryJson, TrySql } from "./Playgrounds"

// ---- small building blocks for the text (kept here: nothing else uses them)

// A diagram: numbered boxes joined by arrows. Side by side on a wide screen, one under the other on a phone.
function Steps({ items }) {
  return (
    <ol className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-stretch" data-testid="diagram">
      {items.map(([title, text], i) => (
        <li key={i} className="flex flex-col items-center gap-1 sm:flex-row sm:gap-2">
          <div className="h-full min-w-32 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
            <p className="font-medium"><span className="mr-1.5 inline-flex size-5 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">{i + 1}</span>{title}</p>
            {text && <p className="mt-1 text-xs text-muted-foreground">{text}</p>}
          </div>
          {i < items.length - 1 && <span aria-hidden className="text-muted-foreground">{"→"}</span>}
        </li>
      ))}
    </ol>
  )
}

// A table of names and meanings. It scrolls sideways inside its own box on a phone.
function Fields({ head = ["Field", "Meaning"], rows }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50"><tr>{head.map((h) => <th key={h} className="px-3 py-1.5 font-medium">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-t">{r.map((c, j) => <td key={j} className={"px-3 py-1.5 align-top " + (j === 0 && typeof c === "string" && c.length <= 32 ? "whitespace-nowrap font-mono text-xs" : "")}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

const Tip = ({ children }) => <p className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm">{children}</p>
const Warn = ({ children }) => <p className="rounded-md border border-amber-500/50 bg-amber-50 px-3 py-2 text-sm text-amber-900">{children}</p>
const List = ({ items }) => <ul className="list-disc space-y-1 pl-5">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
const Num = ({ items }) => <ol className="list-decimal space-y-1 pl-5">{items.map((x, i) => <li key={i}>{x}</li>)}</ol>

export const GROUPS = [
  ["start", "Start here"],
  ["questions", "Questions"],
  ["exams", "Exams"],
  ["candidate", "What the candidate sees"],
  ["help", "When something goes wrong"],
  ["try", "Try it yourself"],
]

// Each topic: id (used in links such as /admin/help?topic=json-route), group, title, body (always on the page, so search can read it)
// and an optional `play` (a playground, built only while the topic is open).
export const TOPICS = [
  // ------------------------------------------------------------------ start
  { id: "big-picture", group: "start", title: "The big picture: from a question to a result", body: (
    <div className="grid gap-3">
      <p>Everything in the platform follows one path. Questions live in the <b>Question bank</b>. An <b>exam</b> picks questions into sections. You add <b>participants</b>, they sit the exam, and you <b>declare</b> the results.</p>
      <Steps items={[
        ["Department", "Decides which question types can be used"], ["Questions", "Typed one by one, or built from AI-made JSON"], ["Exam", "Details, sections, questions, publish"],
        ["Participants", "Names in, logins out"], ["Exam day", "Candidates sit it; you watch the Live monitor"], ["Results", "Calculate, review written answers, declare"],
      ]} />
      <Tip>The fastest way to a first exam: create the exam, press <b>Build with AI</b> on its Questions tab, upload the JSON the AI gives you, add participants, publish.</Tip>
    </div>) },
  { id: "roles", group: "start", title: "Who can do what (roles)", body: (
    <div className="grid gap-3">
      <p>The left menu shows only what your role may use. A Super Admin can do everything.</p>
      <Fields head={["What", "Who may do it"]} rows={[
        ["Create and edit exams, questions, departments; publish", "Test Creator, Org Admin"],
        ["Add participants and logins; extend time, end or re-open an exam; export", "Recruiter, Test Creator, Org Admin"],
        ["See exams, the Live monitor, candidates and reports", "Recruiter, Test Creator, Evaluator, Org Admin"],
        ["Read questions with their answer keys (Question bank)", "Test Creator, Evaluator, Org Admin"],
        ["Mark answers, accept or override AI marks, calculate results", "Evaluator, Org Admin"],
        ["Users, passwords and locks", "Org Admin"],
      ]} />
    </div>) },

  // ------------------------------------------------------------------ questions
  { id: "question-types", group: "questions", title: "The question types and how each one is marked", body: (
    <div className="grid gap-3">
      <p>A department may offer only some of these (for example HR may not offer coding). Marks are set per question.</p>
      <Fields head={["Type", "The candidate", "Marked"]} rows={[
        ["MCQ, one answer", "Picks one option", "Automatically: right = full marks, wrong = 0 (or minus the question's negative marks, if set)."],
        ["MCQ, several answers", "Ticks every right option", "Automatically, strictly: each right option earns its share of the marks, each wrong tick takes 0.25 off, never below 0. Ticking every option scores 0."],
        ["Linked MCQ", "Reads one passage, answers several MCQs on it", "Automatically. Made only in the Question bank editor (it cannot be in the JSON file)."],
        ["Short answer", "Writes a line or two", "Keywords plus an AI comparison with your model answer give a suggested mark. A person confirms it."],
        ["Explained (long) answer", "Writes a paragraph", "AI scores each rubric line (steps of 0.25) and a person confirms."],
        ["Coding", "Writes code in Python, C, C++, Java or JavaScript", "Automatically, by running it on the test cases: open ones the candidate can see, hidden ones only show pass or fail."],
        ["SQL", "Writes a query", "Automatically: the result must match the expected output on every dataset (column names are checked; row order too when you say so)."],
      ]} />
    </div>) },
  { id: "add-one", group: "questions", title: "Add one question by hand", body: (
    <div className="grid gap-3">
      <Num items={[
        <>Open <b>Question bank</b>, press <b>New question</b>.</>,
        "Pick the department, then the type. Only the types the department offers are listed.",
        "Fill in the title, the question text, difficulty, marks and the answer key (right options, model answer, or a reference solution and test cases).",
        <>For coding and SQL press <b>Check reference solution</b> first: it runs your own solution on your cases, so the expected outputs come from real output, never typed by hand.</>,
        <>Press <b>Save</b>. The question can now be added to any exam of that department.</>,
      ]} />
      <p><b>Pictures:</b> under the question text press <b>Add picture</b> (or paste a screenshot into the text box). Each answer option of a choice question has its own small picture button, for questions like "which figure comes next?". A picture is PNG, JPEG, GIF or WEBP, up to 4 under the text, and is made smaller automatically. This works for every type, also coding and SQL.</p>
      <Tip>Many questions? Upload the paper you already have (next topic). Typing 50 questions by hand is slow.</Tip>
    </div>) },
  { id: "paper-upload", group: "questions", title: "Upload your question paper (PDF, Word, Excel, Notepad, photo)", body: (
    <div className="grid gap-3">
      <p>The quickest way to bring a whole paper in. You upload the file you already have; the platform reads it, the AI finds the questions, answers, marks and pictures, and you check the result before anything is added.</p>
      <Steps items={[
        ["Create the exam", "Its department decides which question types can come in"], ["Build with AI", "On the exam's Questions tab"],
        ["Choose the file", "PDF, Word, Excel, Notepad or a photo"], ["Wait", "Three steps show what is happening"],
        ["Review", "Every question, its answer and its pictures"], ["Import", "The ticked questions go into the Question bank and the exam"],
      ]} />
      <Tip>A paper written in the standard format is read <b>exactly</b>, without guessing: the questions, options, marks, pictures and answers come straight from the text, and the AI is used only for coding, SQL and written questions. Download the format as <PaperFormatLinks />. In it: numbered questions (Q1.), marks at the end of the line ([1 mark]), a picture on a line that starts with "Image:" right under its question, picture options written "(a) Image:", options as (a) (b) (c) (d), and <b>the answer right under each question</b> ("Answer: (b)"). A coding question gives its "Sample answer (Python):" and "Test cases:" under it, an SQL question its "Tables:", "Sample data:" and "Answer:". The notes at the top of the file are ignored automatically: you do not have to delete them, and the first line is just your exam title. If you prefer, all answers can instead be listed together at the end under "Answer Key and Solutions".</Tip>
      <p className="font-medium">What can be uploaded</p>
      <List items={[
        <><b>PDF</b> (up to 50 pages). Typed PDFs are best. A scanned page is read as a picture, which is slower and less exact.</>,
        <><b>Word (.docx)</b>. Bold and highlighted options are noticed as the right answer, and pictures stay where they were. An old .doc file: open it and use Save as .docx.</>,
        <><b>Excel (.xlsx)</b> with one question per row, <b>Notepad (.txt)</b>, or a <b>photo</b> (.jpg, .png) of a page.</>,
        "Up to 20 MB and about 40 questions at a time. A longer paper: upload it in parts.",
      ]} />
      <p className="font-medium">Pictures and graphs</p>
      <List items={[
        "A picture in the paper (a graph, a figure, a diagram) is attached to its question. If answer options are pictures, each option gets its own picture.",
        "Maths is written as plain text, for example x^2, (a)/(b), sqrt(x).",
        "A chart drawn inside Word, a drawing on a PDF page, or a figure inside a scanned page cannot be cut out. The review says so: after importing, open the question with the pencil and use Add picture (a screenshot can be pasted).",
      ]} />
      <p className="font-medium">Coding and SQL questions</p>
      <List items={[
        "The paper's reference solution (or reference query) is run for real. The expected outputs come from it, never from the AI, and a solution that does not compile or fails on a case is reported.",
        "A test case the paper only describes (\"maximum size\", \"generated\") is made by a small program, so nothing huge is typed. If a case cannot be made it is left out and the note at the top says which.",
        "If the paper gives no hidden test cases (or no hidden SQL data), the AI writes some and the reference solution is run on them. The note at the top says so: look at them before publishing.",
        "Marks, the sample cases and the input and output formats are taken from the paper. Code copied from a PDF loses its indentation, so the AI restores it and the platform runs it to check.",
      ]} />
      <p className="font-medium">What to check in the review</p>
      <List items={[
        <>The amber note at the top lists what the AI could not do. Read it first.</>,
        <>A question marked <b>Answer chosen by AI, check it</b> had no answer in the paper. The AI guessed; confirm it.</>,
        "A red question has a problem (the message says what). It cannot be added; leave it out, or fix the paper and upload again. The others can still be imported.",
        "Untick any question you do not want. Nothing is saved until you press Import, and then all ticked questions are added together.",
      ]} />
      <Warn>The AI can misread a paper. Always read the questions and the answers before you publish the exam. Wording can be fixed afterwards with the pencil on each question.</Warn>
      <Tip>If the AI is not switched on for the server, the dialog says so. The copy-and-paste route (next topic) still works.</Tip>
    </div>) },
  { id: "json-route", group: "questions", title: "Upload many questions: the AI route (any type)", body: (
    <div className="grid gap-3">
      <p>This is the copy-and-paste way, for when you prefer to use your own ChatGPT or Claude chat (to let the platform do it all, upload the paper instead: see the topic before this one). The platform writes the instructions for the AI; the AI turns your questions into a file in the exact format; the platform checks every question and imports them.</p>
      <Steps items={[
        ["Create the exam", "Fill in its Details first: the prompt carries them"], ["Build with AI", "On the exam's Questions tab: say how many of each type"],
        ["Copy the prompt", "Paste it into ChatGPT or Claude together with your own questions"], ["Get the JSON", "A file, or text you copy"],
        ["Upload or paste it", "The platform checks the WHOLE file"], ["Import", "Only when everything is correct"],
      ]} />
      <List items={[
        "You never write the format yourself: the prompt already contains the rules and one working example per type.",
        "Your questions can be in any form (Word, PDF text, Excel rows, typed). Paste or attach them after the prompt and tell the AI to convert them faithfully.",
        "If one question is wrong the platform lists every problem and saves nothing, so a half-broken file never reaches an exam. Ask the AI to fix the listed problems and upload again.",
        "Written answers (short, long) need a model answer; coding needs a correct reference solution and test inputs; SQL needs the tables and the correct query. The platform runs your solution to get the expected results: the AI never supplies them.",
        "Linked MCQ sets are not part of the file format. Make those in the Question bank.",
      ]} />
      <Tip>Want to see the rules at work first? Open <b>Check my JSON</b> under "Try it yourself" below and break the sample on purpose.</Tip>
    </div>) },
  { id: "json-structure", group: "questions", title: "The JSON file: structure and common fields", body: (
    <div className="grid gap-3">
      <p>One file holds sections, and each section holds questions.</p>
      <p className="font-medium">The shape</p>
      <Sample text={`{
  "format": "globx-exam-questions/1",
  "sections": [
    {
      "title": "Section A: Multiple choice",
      "timer_min": null,
      "questions": [ { ...one question... }, { ...another... } ]
    }
  ]
}`} />
      <p className="font-medium">A complete, valid file with one question of every type</p>
      <p className="text-sm text-muted-foreground">Read from the server, so it is always what the platform accepts today (the AI prompt carries the same examples).</p>
      <SamplePack />
      <p className="font-medium">Fields every question has</p>
      <Fields rows={[
        ["type", "Required. One of: mcq_single, mcq_multi, short, long, coding, sql."],
        ["title", "A short name shown in lists. If you leave it out, the start of the question is used."],
        ["statement", "Required. The question text. Plain text is fine (blank lines make paragraphs). Simple HTML is allowed: p, pre, code, b, i, ul, li, br."],
        ["marks", "Optional. Defaults: MCQ 1, short 2, long 5, coding 10, SQL 10."],
        ["difficulty", "Optional. easy, medium (default) or hard. The Auto populate pools use it."],
        ["skills", "Optional. A list of short tags, for example [\"numeracy\"]."],
        ["negative_marks", "Optional. Marks taken off a wrong single-answer MCQ."],
      ]} />
      <p className="font-medium">Section fields</p>
      <Fields rows={[["title", "The section name candidates see."], ["timer_min", "A whole number of minutes, or null for no section timer."], ["questions", "Required. At least one question."]]} />
      <p className="text-sm text-muted-foreground">Limits: at most 20 sections and 200 questions per file, 2 MB. Next: one topic per type, with a field table and a sample.</p>
    </div>) },
  { id: "json-mcq", group: "questions", title: "JSON for multiple choice (one answer and several answers)", body: (
    <div className="grid gap-3">
      <Fields rows={[
        ["options", "Required. 2 to 8 texts, WITHOUT letters (\"7\", not \"c) 7\")."],
        ["correct", "Required. The letters of the right options: \"a\" is the first option. Exactly one letter for mcq_single; one or more for mcq_multi."],
        ["negative_marks", "Optional. Allowed on both."],
      ]} />
      <p className="font-medium">One answer</p>
      <SampleOf type="mcq_single" />
      <p className="font-medium">Several answers</p>
      <SampleOf type="mcq_multi" />
      <Warn>The most common mistake: a letter in "correct" that does not exist (for example "e" with four options), or letters in the options themselves.</Warn>
    </div>) },
  { id: "json-text", group: "questions", title: "JSON for short and long (written) answers", body: (
    <div className="grid gap-3">
      <p>These are marked with the help of AI, so the platform needs the answer you expect.</p>
      <Fields rows={[
        ["model_answer", "Required. The ideal answer. The AI compares the candidate's answer with it."],
        ["keywords", "Short only, optional. Words the answer should contain. Use | between alternatives: \"retry|retries\"."],
        ["max_words / min_words", "Optional word limits."],
        ["rubric", "Long only, required. A list of {name, max, descriptor}. The max values should add up to the question's marks."],
      ]} />
      <p className="font-medium">Short answer</p>
      <SampleOf type="short" />
      <p className="font-medium">Explained (long) answer</p>
      <SampleOf type="long" />
    </div>) },
  { id: "json-coding", group: "questions", title: "JSON for coding questions", body: (
    <div className="grid gap-3">
      <p>You give the problem, one correct solution, and the test <b>inputs</b>. You never type the expected outputs: the platform runs your solution on each input and records what it prints. If your solution fails its own inputs, the file is refused.</p>
      <Fields rows={[
        ["statement", "Must contain: the problem, \"Input format\", \"Output format\" and \"Constraints\"."],
        ["reference", "Required. {\"language\": \"python\", \"source\": \"...\"} : a correct solution that reads standard input and prints the answer."],
        ["test_cases", "Required. A list of {input, visibility, purpose}. \"open\" cases are shown to the candidate as samples, \"hidden\" cases only report pass or fail. Include at least one of each."],
        ["languages", "Optional. Which languages the candidate may use. Default: python, java, cpp, c, javascript."],
        ["starter", "The code the editor opens with, one entry per allowed language: a short program that reads the input as the statement says."],
        ["time_limit_ms / memory_mb", "Optional. Defaults 2000 ms and 256 MB."],
      ]} />
      <SampleOf type="coding" />
      <Tip>Try the whole thing in <b>Try a coding question</b> below: write an answer and see the open and hidden cases judged.</Tip>
    </div>) },
  { id: "json-sql", group: "questions", title: "JSON for SQL questions", body: (
    <div className="grid gap-3">
      <p>SQL questions run on SQLite. You give the tables, the correct query, and one or more datasets. The expected result comes from running your query.</p>
      <Fields rows={[
        ["schema", "Required. CREATE TABLE statements."],
        ["reference_sql", "Required. The correct query."],
        ["datasets", "Required. A list of {data, visibility}. data = INSERT statements. At least one \"open\" (shown to the candidate) and one \"hidden\"."],
        ["ordered", "Optional. true when the row order must match (use it when the question asks for an ORDER BY)."],
      ]} />
      <SampleOf type="sql" />
      <Tip>Try it in <b>Try an SQL question</b> below.</Tip>
    </div>) },
  { id: "json-mistakes", group: "questions", title: "Common mistakes and what the messages mean", body: (
    <div className="grid gap-3">
      <Fields head={["Message (roughly)", "What to do"]} rows={[
        ["The file is not valid JSON", "A comma, quote or bracket is missing. Ask the AI for the JSON again, or paste it into the Check my JSON playground to find the spot."],
        ["The file needs a 'sections' list", "The top level must be {\"sections\": [...]}."],
        ["'correct' ... is not one of the options", "Use letters a, b, c ... that exist. \"a\" is the first option."],
        ["'model_answer' is missing", "Written answers need an ideal answer for the AI to compare with."],
        ["'rubric' must be a list", "Long answers need rubric lines: name, max, descriptor."],
        ["the reference solution fails on N of M test cases", "Your reference code crashes or times out on one of the inputs. Fix the code or the input."],
        ["the department does not offer ... questions", "That department has the type switched off (Departments screen)."],
        ["At most 200 questions / 20 sections / 2 MB", "Split the file."],
      ]} />
      <p>Every message begins with the section and question number, so you know exactly where to look.</p>
    </div>) },
  { id: "prepare", group: "questions", title: "Getting your questions ready (Word, Excel, an old paper)", body: (
    <div className="grid gap-3">
      <List items={[
        "Keep one question per row or paragraph, with its options and the right answer marked.",
        "Excel sheet of MCQs: columns like Question, A, B, C, D, Correct. Paste the rows into the AI chat after the prompt; it converts them.",
        "Say which questions are coding or SQL and give a correct solution for each; the AI cannot invent a trustworthy one for your syllabus.",
        "Marks, difficulty and skill tags are optional; add them if you want Auto populate pools to use them.",
        "Very long papers: ask the AI for the questions in parts of 30 or 40 and upload each part as its own file; each import adds new sections to the exam.",
      ]} />
    </div>) },

  // ------------------------------------------------------------------ exams
  { id: "create-exam", group: "exams", title: "Create an exam, step by step", body: (
    <div className="grid gap-3">
      <Steps items={[["New exam", "Exams, then New exam"], ["Details", "Title, department, time, rules"], ["Questions", "Sections and questions"], ["Participants", "Names in, logins out"], ["Publish", "Opens it to the candidates"]]} />
      <Num items={[
        <>Open <b>Exams</b>, press <b>New exam</b>, fill in the Details and press <b>Create exam</b>.</>,
        <>On the <b>Questions</b> tab press <b>Add section</b>, then <b>Add questions</b> (from the bank), <b>Auto populate</b> (random pick) or <b>Build with AI</b>.</>,
        <>On the <b>Participants</b> tab type the names and press <b>Create logins</b>.</>,
        <>Press <b>Publish</b>. The platform refuses to publish an exam that is incomplete and tells you what is missing.</>,
      ]} />
    </div>) },
  { id: "exam-details", group: "exams", title: "Every field on the exam's Details tab", body: (
    <div className="grid gap-3">
      <Fields head={["Setting", "What it does"]} rows={[
        ["Department", "Decides which question types you can use."],
        ["Title, Description, Instructions", "Candidates read the instructions on the page before the exam starts."],
        ["Opens at, Closes at", "The window in which candidates can start. Results are calculated automatically after the closing time. With no closing time you press Calculate yourself."],
        ["Time allowed per candidate", "Minutes from the moment each person starts."],
        ["Pass mark", "Total marks needed to pass."],
        ["Seconds each question stays on screen before Next unlocks", "The reading time. 0 turns it off. New exams start at 5."],
        ["Shuffle question order / answer options", "Each candidate sees a different order."],
        ["Show the result to the candidate", "Whether the candidate sees a score after you declare."],
        ["Proctoring on", "Switches the rules below on. Camera and face check, full screen, blocking copy/paste and right-click, blocking a second screen, entire-screen sharing, live view for the invigilator."],
        ["Window or full-screen leaves allowed", "How many times a candidate may leave the exam window or full screen before the limit is reached."],
        ["Face warnings before the exam ends", "After this many warnings the exam ends and the login is locked."],
        ["Evidence kept", "What is recorded (pictures, video) and for how many days."],
      ]} />
      <Warn>Test the camera rules on one laptop first. Turn Proctoring on only when the room and computers are ready.</Warn>
    </div>) },
  { id: "sections-pools", group: "exams", title: "Sections, timers and random pools", body: (
    <div className="grid gap-3">
      <List items={[
        "A section groups questions (for example MCQ, then Coding). Each section can have its own timer; when it runs out the candidate moves on and cannot go back to it if navigation is locked.",
        <><b>Add questions</b> picks exact questions from the bank. <b>Auto populate</b> picks at random for each candidate: choose the department, the question types, how many easy / medium / hard, and optionally tags.</>,
        "An exam can be edited only while it is a draft. To change a published exam, Unpublish it first (only when nobody is taking it).",
        "A question fixed after the exam started changes for candidates who have not finished; finished candidates keep what they saw.",
      ]} />
    </div>) },
  { id: "participants", group: "exams", title: "Participants and the login sheet", body: (
    <div className="grid gap-3">
      <Num items={[
        <>On the <b>Participants</b> tab type <b>one person per line</b>. A line can be a name, or <code>Name, email</code>. The email is optional.</>,
        <>Press <b>Create logins</b> and confirm. Each person gets a username and a password.</>,
        <>The passwords are shown <b>once</b>. Press <b>Download all as CSV</b> or Print before you leave the page.</>,
        <>Lost a password? Use <b>Get a fresh login sheet</b> (everyone who has not started gets a new password) or <b>New password</b> for one person.</>,
      ]} />
      <p>Per participant you can: <b>Extend time</b>, <b>End exam now</b> (submits what they have), <b>Re-open exam</b> (a fresh attempt after a technical problem or an unfair lock), <b>Cancel invitation</b>, <b>New password</b>. Most of them ask for a reason.</p>
    </div>) },
  { id: "exam-day", group: "exams", title: "On the day: the Live monitor", body: (
    <div className="grid gap-3">
      <List items={[
        <>Open <b>Live monitor</b> and pick the exam. You see who is in progress, their warnings and time left.</>,
        <>With <b>Live view for the invigilator</b> on, each tile shows the candidate's camera and screen. A tile that says <b>Live</b> is connected; <b>Connecting</b> or <b>Not connected</b> means the picture is not arriving.</>,
        "You can send a message to a candidate, extend their time, or end their exam.",
        "Do a practice run with 5 to 7 real laptops before the real exam, and check every tile says Live.",
        <b key="d">Do not update or restart the server while an exam is running.</b>,
      ]} />
    </div>) },
  { id: "results", group: "exams", title: "After the exam: calculate, review, declare", body: (
    <div className="grid gap-3">
      <Steps items={[["Calculate", "Automatic after the closing time, or press the button"], ["Review", "Open written answers: accept or change the suggested marks"], ["Declare", "Candidates can now see their result"], ["Export", "CSV or Excel"]]} />
      <List items={[
        <><b>Calculate results</b> marks everything from the saved answers again. Marks you set by hand are kept.</>,
        <>Written answers show an AI suggestion. <b>Accept all suggested marks</b> takes them all; or open a candidate and change a mark yourself. <b>Mark with AI again</b> replaces the current mark, including a hand mark.</>,
        <>People who did not attend, and people whose exam was ended, are recorded too.</>,
        <><b>Declare results</b> shows candidates their score. <b>Withdraw results</b> hides it again. A mark changed later shows the candidate the new score.</>,
        "Open any candidate for the full report: answers, code verdicts, proctoring timeline and pictures.",
      ]} />
    </div>) },

  // ------------------------------------------------------------------ candidate
  { id: "candidate-flow", group: "candidate", title: "What the candidate goes through", body: (
    <div className="grid gap-3">
      <Steps items={[["Sign in", "Username and password from the login sheet"], ["Your exams", "Press Start (or Resume)"], ["Check-in", "Rules, camera, screen sharing"], ["The exam", "Sections, palette, timer"], ["Submit", "End exam, then a thank-you page"], ["Result", "After you declare, if enabled"]]} />
      <List items={[
        "The timer is the server's, so changing the computer's clock changes nothing. If the page closes or the power goes, signing in again and pressing Resume continues where they were.",
        "Answers are saved as they are given. Mark for review only flags a question for the candidate; it does not change the answer.",
        "Coding and SQL answers run on the platform's isolated judge. Run tries the open samples; Submit judges all cases.",
        "Leaving the window, a face that is not visible, or a second screen can raise warnings if you switched those rules on.",
      ]} />
    </div>) },
  { id: "reading-time", group: "candidate", title: "The minimum reading time", body: (
    <div className="grid gap-3">
      <p>When set (5 seconds for new exams), a question must stay on screen for that long the first time it is opened before the candidate can move forward. The button shows a countdown, for example "Save and next (4s)".</p>
      <List items={[
        "Going back, marking for review, answering and End exam are never blocked.",
        "A question that has had its time stays free. After a refresh, questions already answered are free.",
        "A section whose time is over never waits.",
        "It is a rule on the screen, not a server check. Grading uses saved answers only.",
      ]} />
    </div>) },

  // ------------------------------------------------------------------ trouble
  { id: "troubleshooting", group: "help", title: "Problems and what to do", body: (
    <div className="grid gap-3">
      <Fields head={["What you see", "What to do"]} rows={[
        ["A red bar: \"Coding and SQL questions are switched off: the isolated judge is not set up\"", "Tell the administrator: the code judge container is not running. Do not run a coding exam until it is."],
        ["A candidate lost their password", "Participants tab: New password for that person, or Get a fresh login sheet."],
        ["A candidate is locked out after face warnings", "Check the proctoring timeline in their report; if it was unfair or a technical fault, use Re-open exam."],
        ["Results do not show", "Press Calculate results, review written answers, then Declare results."],
        ["Participants error about names or emails", "One person per line. A comma separates a name from an email, not two people."],
        ["The page says the server needs a restart", "The screens are newer than the running server. Ask the administrator."],
        ["A tile in Live monitor does not say Live", "The candidate's laptop or network is blocking the live connection; ask them to reload, and check it in your practice run."],
        ["The tab shows the old icon or name", "Press Ctrl+F5 once."],
      ]} />
    </div>) },

  // ------------------------------------------------------------------ playgrounds
  { id: "try-json", group: "try", title: "Check my JSON (nothing is saved)", body: <p>Paste or edit a question file and see exactly what the real import would say. Good for learning the format and for finding a mistake in a file the AI gave you.</p>, play: <TryJson /> },
  { id: "try-exam", group: "try", title: "Try the exam screen (a sample exam)", body: <p>Answer three sample questions the way a candidate does, finish, and see how each is marked. The marks come from the platform's real marking rule.</p>, play: <TryExam /> },
  { id: "try-coding", group: "try", title: "Try a coding question: write an answer and run it", body: <p>See how a coding question is set and answered: a statement, visible sample cases, hidden cases, and your code judged on all of them.</p>, play: <TryCoding /> },
  { id: "try-sql", group: "try", title: "Try an SQL question: write a query and run it", body: <p>See how an SQL question is set and answered: a table with data, the expected output, and your query compared with it.</p>, play: <TrySql /> },
]
