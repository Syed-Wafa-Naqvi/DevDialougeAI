# DevDialogue AI

An interactive, conversation-driven specification elicitation and codebase generation engine designed to eliminate ambiguity in software prototyping.

## Features
- **Dialogue-Driven Interviewing (Mode 1)**: Structured questioning to define modules, dependencies, database requirements, and integration adapters before code generation.
- **Incremental Code Generation (Mode 2)**: Module-by-module generation with interactive developer feedback loops.
- **Ambiguity Detection**: Automatic identification of conflicting constraints in product specifications.
- **Professional Dark/Light Modes**: Custom OpenAI/ChatGPT inspired dark palette (soft greens/blues on dark greys) and high-contrast light mode.
- **Secure SMTP OTP Sign-Up**: Verification codes with dynamic 2-minute countdown and resending controls.

## Tech Stack
- **Backend**: Django 6.0
- **Frontend**: HTML5, Vanilla CSS3 (monochrome/slate custom variables), JavaScript (Lucide icons)
- **SMTP**: Django Mail Service with secure OTP dispatching

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Syed-Wafa-Naqvi/DevDialougeAI.git
   cd DevDialougeAI
   ```

2. Set up a virtual environment:
   ```bash
   python3 -m venv env
   source env/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure your `.env` file with the required SMTP credentials.

5. Run migrations and compile assets:
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

6. Start the server:
   ```bash
   python manage.py runserver
   ```
