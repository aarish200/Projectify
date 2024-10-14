import os
import openai
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, session , jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import random
from flask_migrate import Migrate  # For managing database migrations
import logging
import re

# Load environment variables
load_dotenv()
openai.api_key = ''
app = Flask(__name__)
app.secret_key = '27b07e50eb3e7616aa64746f5fda2e3d83d4e7e2081b5a848284c905ba444e74' 

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatbot.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
migrate = Migrate(app, db)  # Initialize Flask-Migrate

# Configure logging settings
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# === Database Models ===

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    messages = db.relationship('Message', backref='user', lazy=True)
    user_data = db.relationship('UserData', backref='user', uselist=False)
    sessions = db.relationship('ChatSession', backref='user', lazy=True)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('Message', backref='session', lazy=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    role_info = db.Column(db.String(50))  # Stores the role information

class UserData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data = db.Column(db.PickleType)  # Stores user's answers to role questions

# Flask-Login user loader
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Define greeting messages and welcome message
GREETING_MESSAGES = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
WELCOME_MESSAGE = "Hello! How can I assist you with your projects today?"


# Questions to ask the user based on the role
ROLE_QUESTIONS = {
    "Generate Project Ideas": [
        "Sure, I'd be happy to help generate project ideas. Could you provide some details about your interests, budget, timeframe, and experience level?"
    ],
    "In-depth Knowledge": [
        "Absolutely! What specific topic would you like in-depth information on?"
    ],
    "Research AI": [
        "Certainly! What area of AI research are you interested in exploring?"
    ],
    "Research Format": [
        "Sure, I can help with the research format. Could you specify the topic or area your research is focused on?"
    ],
    "Research-depth Knowledge": [
        "Understood! Please share the specific content areas you'd like to delve into."
    ],
    "Project Counselor": [
        "I'm here to help with your projects. Please describe what you're working on or any challenges you're facing."
    ],
}

# === Intent Classification ===

def classify_intent(message):
    message = message.lower()

    # Define greeting messages
    GREETING_MESSAGES = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
    # Split message into words
    words = set(message.split())

    # Check for single-word greetings
    if words & GREETING_MESSAGES:
        return "Greeting"

    # Check for multi-word greetings
    for greeting in GREETING_MESSAGES - words:
        if greeting in message:
            return "Greeting"

    # Define specific intent terms
    specific_terms = {
        "Generate Project Ideas": [
            "project idea", "developing projects", "project suggestions", 
            "generate project ideas", "i need a project idea"
        ],
        "In-depth Knowledge": [
            "depth in knowledge", "detailed explanation", "learn more about", 
            "in-depth knowledge"
        ],
        "Research AI": [
            "research idea", "ai research", "study ai topics", "research ai"
        ],
        "Research Format": [
            "research format", "structure research", "writing research paper"
        ],
        "Research-depth Knowledge": [
            "research content", "deep dive into research", "research-depth knowledge"
        ],
        "Project Counselor": [
            "project help", "project counselor", "project assistance"
        ],
        "Yes": ["yes", "yeah", "yep"],
        "No": ["no", "nope", "nah"],
    }

    # Check for specific intent terms using regex
    for intent, terms in specific_terms.items():
        for term in terms:
            # Escape special characters in term and add word boundaries
            pattern = r'\b' + re.escape(term) + r'\b'
            if re.search(pattern, message):
                return intent

    # Default intent
    return "General Assistant"


    # Default intent if no specific intent or greeting is detected
    return "General Assistant"

# === Response Generation Functions ===

def generate_response(user_message):
    """
    Unified function to handle user messages, role-based conversations, and general assistance.
    """
    # Classify user intent
    intent = classify_intent(user_message)
    logging.debug(f"Intent identified: {intent}")

    # Retrieve previous intent and role-related session data
    previous_intent = session.get('previous_intent', '')
    role = session.get('current_role', None)
    role_questions_asked = session.get('role_questions_asked', False)

    # Retrieve current conversation history
    conversation_history = get_current_conversation_history()

    # Handle Yes/No responses for ongoing role-related conversation
    if intent in ["Yes", "No"] and role:
        session['previous_intent'] = intent
        if intent == "Yes":
            # Continue the conversation with the current role
            return continue_role(user_message, conversation_history, role)
        else:
            # End role-related conversation and reset session data
            session.pop('current_role', None)
            session['role_questions_asked'] = False
            session.pop('pending_questions', None)
            session.pop('role_answers', None)
            return "What else can I help you with?"

    # Handle ongoing role-related questions if no questions have been asked yet
    elif not role_questions_asked and role:
        return handle_role_questions(user_message, role)

    # Check if the user message matches any role-related questions
    else:
        if intent in ROLE_QUESTIONS:
            # Start role-related conversation and ask questions
            session['previous_intent'] = intent
            session['current_role'] = intent
            session['role_questions_asked'] = False
            return ask_role_questions(intent)

        # If no specific role is detected, treat the query as general assistance
        else:
            session['previous_intent'] = "General Assistant"
            session.pop('current_role', None)
            session['role_questions_asked'] = False
            return general_assistant(user_message, conversation_history)

def ask_role_questions(role):
    questions = ROLE_QUESTIONS.get(role, [])
    if questions:
        session['pending_questions'] = questions
        session['role_answers'] = []
        return questions[0]
    else:
        session['role_questions_asked'] = True
        return generate_role_response("", role)

def handle_role_questions(user_message, role):
    pending_questions = session.get('pending_questions', [])
    role_answers = session.get('role_answers', [])

    role_answers.append(user_message)
    session['role_answers'] = role_answers

    if len(role_answers) < len(pending_questions):
        next_question = pending_questions[len(role_answers)]
        return next_question
    else:
        session['role_questions_asked'] = True
        # Store the answers in user_data
        user_data = current_user.user_data
        if not user_data:
            user_data = UserData(user_id=current_user.id, data={})
            db.session.add(user_data)
        if not user_data.data:
            user_data.data = {}
        user_data.data[role] = role_answers
        db.session.commit()
        details = " ".join(role_answers)
        # Retrieve the updated conversation history
        conversation_history = get_current_conversation_history()
        return generate_role_response(details, role, conversation_history)

def continue_role(user_message, conversation_history, role):
    if not session.get('role_questions_asked', False):
        return handle_role_questions(user_message, role)
    else:
        # Retrieve user's data
        user_data = current_user.user_data
        user_details = ""
        if user_data and user_data.data and role in user_data.data:
            user_details = " ".join(user_data.data[role])
        details = user_message + " " + user_details
        return generate_role_response(details.strip(), role, conversation_history)

def greeting_response(user_message):
    responses = [
        "Hello! How can I assist you with your projects today?",
        "Hi there! What can I help you with regarding your projects?",
        "Greetings! How may I assist you today?"
    ]
    # Directly return a greeting without thinking or delay
    return random.choice(responses)

def openai_response(prompt, conversation_history, max_tokens=1500):
    try:
        messages = []
        # Filter and include the last 5 messages
        for message in conversation_history[-5:]:
            # Exclude messages with code or disallowed content
            if '\n' in message.content or '<code>' in message.content:
                continue
            if len(message.content) > 1000:
                continue
            role = 'assistant' if message.role == 'Assistant' else 'user'
            messages.append({'role': role, 'content': message.content})

        messages.append({'role': 'user', 'content': prompt})

        # Create a response from OpenAI's ChatCompletion
        response = openai.ChatCompletion.create(
            model='gpt-4',
            messages=messages,
            max_tokens=1000,  # Use max_tokens from the function parameter
            n=1,
            stop=None,
            temperature=0.6,
        )

        # Extract the assistant's response
        assistant_response = response['choices'][0]['message']['content']
        return assistant_response.strip()
    
    except openai.error.AuthenticationError:
        logging.error("Invalid API key provided.")
        return "Error: Invalid API key."
    
    except openai.error.RateLimitError:
        logging.error("API rate limit exceeded.")
        return "Error: Rate limit exceeded, try again later."
    
    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error: {e}")
        return "An unexpected error occurred while generating a response."
    
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return "An unexpected error occurred while generating a response."
    
def generate_role_response(details, role, conversation_history):
    function_map = {
        "Generate Project Ideas": generate_project_ideas,
        "In-depth Knowledge": in_depth_knowledge,
        "Research AI": research_ai,
        "Research Format": research_format,
        "Research-depth Knowledge": research_depth_knowledge,
        "Project Counselor": project_counselor,
        "General Assistant": general_assistant,
    }
    func = function_map.get(role, general_assistant)
    response = func(details, conversation_history)
    response += " Do you have any queries about the above response?"
    return response

def generate_project_ideas(details, conversation_history):
    prompt = f"""Generate 10 specific, innovative project ideas based on the user's input:{details}. Ensure that the ideas are creative and align with the user's focus area, budget, and team size.
    Generate innovative and detailed project ideas based on the following specifications and the {details} Take into consideration their budget and their timeframe along with the experience they have. Adjust the ideas according to their experience if it is their first project or some experince then diffeent ideas and if they are experinced then the ideas should more complex.:  You also posses the knowledge of every succecful project and use it to answer any question or doubt by the user on the project idea, project depth or doubts and queries overall and also give inspiration to the user by taking related project to their ideas as examples. So Generate 10 specific, very innovative, creative, and detailed project ideas taking into account the details above. For each project, include
    previous projects that have been successful before by students:
    1. Brief description: Define goals and core concept in 2 lines just like an overview of the project.
    2. Expected impact: Short-term and long-term benefits.
    3. Necessary resources: Materials, human resources, and technology.
    4. Execution plan: Key steps and timeline in structure of months or weeks.
    5. Challenges: Provide a brief overview of the project idea to make the Potential risks and mitigation strategies understandable. Be transparent and honest and priortize the most critical challenges and explain these challenges affect the project's timeline , cost ,  quality or overall success. Furthermore, use specif examples to illustrate challenges with specific examples or scenarios. Also support your points by offering data and evidence.
    6. Budget: Cost estimates and funding sources. Ensure that this does not exceed the budget in the details above.
    7. Success metrics: Using SMART acronym explain the criteria and measurement methods of the project. You must make sure that every stage is explained in a defined manner that gives the user the exact idea for the success metrics of the project.
    8. A relevant example of a similar, existing project. give a well defined project brief of this existing project.
    The list is just for your reference, give a well-structured compendious and concise paragraph that explicates each project. Give about 100 words per project and make sure you complete 10 projects by providing the most amount of information in least amount of words.
     Make sure that all of these are fully put in the max token limit and none of the information is missed out
    """
    return openai_response(prompt, conversation_history)

def in_depth_knowledge(details, conversation_history):
    prompt = f""""
    "Provide a detailed guide based on the {details} Include planning, resource allocation, execution, obstacles, and evaluation.
    Based on the users project mentioned the 
    You have the knowledge and scale the projects on local, national, and international levels and cater completely to the needs of the user.
    The guide should include comprehensive details and consider the demographic situations of the user, with an emphasis on adhering to the budget and resources. Ensure the response aligns with the specific project chosen by the user.
    .In all the sections take data from previous successful projects in the same area, consider what president made them successfull and incoorperate them in your response:
     1. Planning Phase(it should be so accurate the user will be able to visualise the idea):
       a. Define the project scope and specific objectives in detail, including how they align with the SDG Goal and the purpose of the project along with the demographic conditions of the location entered byt the user.
       b. Identify and describe key stakeholders, including their roles and responsibilities, and how they will be engaged.
       c. Develop a detailed project plan with a Gantt chart or similar timeline, outlining major milestones and deliverables.
       d. Create a comprehensive risk management plan, including risk identification, assessment, mitigation strategies, and contingency plans.Make sure you understand what types of problem the person who is using this model will face by the data he entered
    2. Resource Allocation:
       a. List all necessary resources, including materials, human resources, technology, and facilities, and describe their acquisition or sourcing.Make all the resources cost effecient and find the best resouerces that can save the most amount of money.Dont forget about the currency that the user uses.
       b. Develop a detailed budget plan, itemizing all costs, funding sources, and potential funding opportunities.
       c. Make sure that the resources are apt to the level the project wants to the reach and the demographic location too
       Also make sure all the resourse cost are under the toal budget cost. 
    3. Execution Phase:
       a. Give a prpoer timeline using the required temporal units(be as specific as possible)when providing a step by step breakdown of tasks and activities required to execute the project.Also make sure everything is in points.
       b. Identify key milestones and deliverables, specifying their importance, deadlines, and how progress will be measured.
       c. Detail monitoring and reporting mechanisms to track progress, ensure accountability, and make adjustments as needed.
       d. Develop a communication plan to keep stakeholders informed and engaged throughout the project, including regular updates and feedback mechanisms.
    4. Potential Obstacles:
       a. Identify 4-5 specific main potential risks and challenges in detail in points, including their likelihood, impact, and how they could affect project execution.
       c. Propose strategies and solutions for overcoming common obstacles, drawing on best practices, case studies, and previous experiences.
    5. Evaluation and Improvement:
       a. Define clear success metrics and explain how to measure them effectively, including qualitative and quantitative criteria.
       b. Also give a precise information on the impact to the community.Try to also make one line pointers on the imapcted demographic.
       c. Provide 3-4 unique, creative and innovative recommendations for future projects, giving detailed examples and actionable insights.
    6. Cost and Funding:
       a. Identify the initial and running costs of the project, breaking them down into categories and providing cost estimates. Also provide the materials required for the project and the genral cost of the material next to it.
       b. Explore various funding sources, including grants, sponsorships, crowdfunding, and community fundraising, and how to secure them.
       c. Suggest ways to reduce costs, such as leveraging in-kind contributions, partnerships, and cost-sharing strategies.
    7. Team Management:
       a. List the key team members needed for the project, specifying their roles, responsibilities, and how they will be selected and managed.
       b. Outline the initial steps each team member will undertake, including onboarding, training, and task assignments.
       c. Provide statistical contributions and performance metrics for team members to track their impact and productivity.
       d. Create a comprehensive to-do list for the project, including tasks, deadlines, and responsible parties.
    8. genrate to do tasks list of 10 steps points crisp and short. 
      Ensure that the response is tailored to the specific project chosen by the user and provides actionable insights and practical advice that aligns with the project's goals and constraints. Learn from previous successful projects that are started by students in the same sector and learn from those ideas and modify this idea in the same way.
      Make sure that all of these are fully put in the max token limit and none of the information is missed out"
    """
    return openai_response(prompt, conversation_history)

def research_ai(details, conversation_history):
    prompt = f"""" 
    Generate 10 specific, innovative research ideas based on the user's input:

    {details}

    Ensure that the research topics are creative and align with the user’s academic level (high school or undergraduate), focus area, and available resources. Provide innovative, detailed research topics with explanations that are aligned to the user’s experience and available timeframe.

    Adjust the complexity of the ideas based on their level of experience. For beginners, offer research topics that focus on building foundational understanding. For intermediate-level students, suggest moderately complex topics with real-world applications. For experienced researchers, propose more advanced topics requiring in-depth analysis, critical thinking, and mathematical/logical reasoning.

    You possess detailed knowledge of successful research projects conducted by high school and undergraduate students, which should be used to inspire and inform the user’s research topic and methodology. For each research idea, include:

    - Brief description: Provide a concise, 2-3 sentence summary of the research aim and core research question.
    - Expected impact: Highlight the short-term and long-term contributions or potential significance of the research.
    - Research framework: Provide a suggested structure, including sections like literature review, methodology, data collection, and analysis.
    - Mathematical/Logical approach: Specify if the research involves mathematical models, logical reasoning, or computational techniques.
    - Challenges and considerations: Outline potential research difficulties, limitations, and mitigation strategies.
    - Resources and tools: Suggest databases like Google Scholar and tools like Overleaf for paper drafting, along with other relevant tools or software.
    - Example of similar past research: Provide a brief summary of a similar, successful research project conducted by a student at the same academic level.
    - Success metrics: Explain how to measure the success of the research, using clear criteria like research depth, originality, and impact.

    Ensure the response fits within the token limit while delivering concise and specific research ideas that inspire and guide the user.

    """
    return openai_response(prompt, conversation_history)

def research_format(details, conversation_history):
    prompt = f"""
    Here's a general framework for structuring a research paper based on your input:

    {details}

    1. Title Page
    - Title of the Research: A concise and descriptive title that encapsulates the main theme of the research.
    - Your Name: Author's name.
    - Institutional Affiliation: Name of your institution or university.
    - Course Name and Code: Details of the course for which the research is conducted.
    - Instructor's Name: Full name of the course instructor.
    - Date: Submission date.

    2. Abstract
    - Purpose: A brief overview of the research aim.
    - Methods: Summary of the methodology used.
    - Results: Key findings or results of the study.
    - Implications: The significance of the findings.
    - Keywords: List of 3-5 keywords relevant to the study.

    3. Introduction
    - Background information and context.
    - Problem statement and research questions.
    - Objectives of the study.
    - Significance and scope.

    4. Literature Review
    - Summarize existing research related to your topic.
    - Identify gaps that your research aims to fill.
    - Theoretical framework.

    5. Methodology
    - Research design and approach.
    - Data collection methods.
    - Data analysis procedures.
    - Ethical considerations.

    6. Results
    - Presentation of findings.
    - Use tables, figures, and graphs as needed.

    7. Discussion
    - Interpret the results.
    - Compare findings with existing literature.
    - Implications of the results.

    8. Conclusion
    - Summarize the key findings.
    - Discuss limitations of the study.
    - Suggest areas for future research.

    9. References
    - List all sources cited in your research, formatted according to the required citation style.

    10. Appendices (if necessary)
        - Additional material such as raw data, consent forms, questionnaires.

    Each section contains specific guidelines on what to include, ensuring that your research is structured coherently.

    You have the expertise to elevate your research paper to unparalleled heights, making it impactful on both academic and practical fronts. This guide delves into every facet of your project, tailored to meet the intricacies of your subject matter while maximizing your available resources and budget. Let’s ensure your research not only meets but exceeds expectations.

    [Include any additional details or customization based on the user's needs.]
    """
    return openai_response(prompt, conversation_history)

def research_depth_knowledge(details, conversation_history):
    prompt = f"""

    Provide a detailed guide for structuring your research project based on the following details:

    {details}

    You have the expertise to elevate your research paper to unparalleled heights, making it impactful on both academic and practical fronts. This guide will delve into every facet of your project, tailored to meet the intricacies of your subject matter, while maximizing your available resources and budget. Let’s ensure your research not only meets but exceeds expectations.

    1. Conceptualization Phase (Imagine your research taking form):
    - Define the Research Scope: Elaborate on your research questions, objectives, and how they align with current trends and academic discourse. Reflect on the demographic and contextual significance of your topic, ensuring it resonates with relevant stakeholders.
    - Identify Key Stakeholders: Detail the main contributors and audiences for your research—this includes mentors, peers, and academic institutions—defining their roles and how you plan to engage them throughout your research journey.
    - Craft a Comprehensive Research Plan: Develop a meticulous roadmap that outlines major milestones, methodologies, and expected outcomes. Visualize your path with a detailed timeline, enhancing clarity and focus.
    - Risk Management Strategy: Identify potential challenges in your research, such as data limitations or ethical concerns, and propose proactive strategies for mitigation. Understanding these hurdles is key to achieving your research goals.

    2. Resource Allocation:
    - List Essential Resources: Enumerate materials, databases, human resources, and technological tools needed for your research. Seek cost-efficient options and resources that provide the most value, considering your local currency and budget constraints.
    - Develop a Detailed Budget Plan: Itemize all projected expenses, explore funding avenues, and consider grants, sponsorships, and university resources that could support your research.
    - Ensure Resource Relevance: Confirm that your resources are appropriate for your research scope and contextual needs, all while maintaining budgetary limits.

    3. Execution Phase:
    - Timely Task Breakdown: Provide a step-by-step breakdown of research activities, ensuring each task is clearly defined with specific deadlines. Precision here will help you stay on track.
    - Identify Milestones and Deliverables: Specify key outcomes and their significance, detailing how each will be evaluated and measured throughout your research process.
    - Monitoring and Reporting Mechanisms: Establish methods to track your progress, ensuring accountability and adaptability. This will help you adjust your approach as necessary.
    - Communication Plan: Design a communication strategy to keep stakeholders engaged, incorporating regular updates and opportunities for feedback to enhance collaboration.

    4. Potential Obstacles:
    - Identify Key Risks: Outline 4-5 major challenges you may face, assessing their likelihood and potential impact on your research.
    - Propose Strategic Solutions: Draw from best practices and previous studies to recommend innovative strategies for overcoming these obstacles.

    5. Evaluation and Improvement:
    - Define Success Metrics: Outline clear criteria for evaluating your research’s success, encompassing both qualitative and quantitative measures.
    - Community Impact Insight: Highlight the anticipated effects of your research on the target demographic, succinctly conveying its significance.
    - Innovative Recommendations: Suggest 3-4 creative pathways for future research, bolstering your recommendations with actionable insights and examples from existing studies.

    6. Cost and Funding:
    - Break Down Costs: Identify initial and ongoing expenses related to your research, categorizing them for clarity. Include estimates for essential materials.
    - Explore Funding Opportunities: Investigate diverse funding options available for your research, detailing how to approach these sources effectively.
    - Cost Reduction Strategies: Propose methods to minimize expenses, such as leveraging partnerships or utilizing university resources.

    7. Team Management:
    - Identify Key Team Members: Specify essential contributors to your research, clarifying their roles and how you will manage collaboration.
    - Outline Initial Steps: Provide a structured plan for onboarding and training each team member, ensuring everyone is aligned and informed.
    - Performance Metrics: Develop criteria to evaluate the contributions and productivity of team members, enhancing accountability and motivation.
    - Comprehensive To-Do List: Create a detailed task list that outlines specific responsibilities, deadlines, and accountability for each aspect of your research project.

    """
    return openai_response(prompt, conversation_history)

def project_counselor(details, conversation_history):
    prompt = f"As a project counselor, provide advice and guidance on the following project:\n{details}"
    return openai_response(prompt, conversation_history)

def general_assistant(details, conversation_history):
    prompt = details
    return openai_response(prompt, conversation_history)

@app.route('/clear-chat', methods=['POST'])
def clear_chat():
    # Clear chat messages stored in the session
    session.clear()  # Clear the entire session
    session['messages'] = []  # Set an empty list for new messages

    # Regenerate a new session ID
    session.modified = True  # This indicates that the session has been modified
    session.permanent = True  # Make sure session persists (optional, based on your settings)

    # You can add any other session variables if needed
    session['user'] = 'new_user'

    return jsonify({"status": "chat cleared", "new_session_id": request.cookies.get('session')})

def new_chat():
    # Clear chat messages stored in the session
    session.pop('messages', None)  # Clear the session messages
    session['messages'] = []  # Set an empty list for new messages
    return jsonify({"success": True})  # Simplified response

def get_current_conversation_history():
    # Retrieve the messages from the current chat session
    current_session_id = session.get('chat_session_id')
    if not current_session_id:
        # Create a new chat session
        new_session = ChatSession(user_id=current_user.id)
        db.session.add(new_session)
        db.session.commit()
        session['chat_session_id'] = new_session.id
        return []
    else:
        messages = Message.query.filter_by(
            session_id=current_session_id
        ).order_by(Message.timestamp).all()
        return messages

# === Routes ===

@app.route('/')
def home():
    return redirect(url_for('chat'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        username = request.form['username']
        password_input = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password_input):
            login_user(user)
            # Start a new chat session
            session.pop('chat_session_id', None)
            return redirect(url_for('chat'))
        else:
            return render_template('login.html', error="Invalid username or password.")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        username = request.form['username']
        password_input = request.form['password']
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error="Username already exists.")
        else:
            user = User(username=username)
            user.set_password(password_input)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            # Start a new chat session
            session.pop('chat_session_id', None)
            return redirect(url_for('chat'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()  # Clear all session data
    logout_user()
    return redirect(url_for('login'))

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    if request.method == 'POST':
        user_input = request.form['message']

        # Retrieve current chat session ID
        current_session_id = session.get('chat_session_id')
        if not current_session_id:
            # Create a new chat session
            new_session = ChatSession(user_id=current_user.id)
            db.session.add(new_session)
            db.session.commit()
            session['chat_session_id'] = new_session.id
            current_session_id = new_session.id

        # Save user's message to the database
        user_message = Message(
            session_id=current_session_id,
            user_id=current_user.id,  # Added user_id here
            role='User',
            content=user_input
        )
        db.session.add(user_message)
        db.session.commit()

        # Generate response
        assistant_response = generate_response(user_input)

        # Save assistant's response to the database
        bot_message = Message(
            session_id=current_session_id,
            user_id=current_user.id,  # Added user_id here
            role='Assistant',
            content=assistant_response,
            role_info=session.get('current_role', 'General Assistant')
        )
        db.session.add(bot_message)
        db.session.commit()

        return redirect(url_for('chat'))

    # For GET requests, only show messages from the current session
    messages = get_current_conversation_history()
    return render_template('index.html', messages=messages)

# Error handler
@app.errorhandler(401)
def unauthorized(e):
    return redirect(url_for('login'))

# Run the application
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
