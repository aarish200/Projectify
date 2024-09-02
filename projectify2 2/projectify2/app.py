import openai
from flask import Flask, request, render_template, jsonify
import logging
import os

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.DEBUG)

openai.api_key = ''
# Global messages
WELCOME_MESSAGE = "Welcome! Please provide the SDG Goal:"
BUDGET_MESSAGE = "Could you please share the budget for your project? Kindly specify the currency."
GROUP_SIZE_MESSAGE = "How many people will be involved in this project? Please provide the group size."
PURPOSE_MESSAGE = "Is this your first project, or do you have prior experience in similar initiatives? If you have prior experience, please briefly describe it."
DESCRIPTION_MESSAGE = "Could you describe your vision for the project? What specific goals or outcomes are you aiming for?"
LEVEL_MESSAGE = "Please specify the project's scope: Is it local, state-level, national, or international?"
TIME_MESSAGE = "How long would you like the project process to take?"
LOCATION_MESSAGE = "Where will the project be based? Please provide the specific location, including city and country."
EDUCATION_LEVEL = "What level of education are you currently pursuing?"
PROJECT_IDEAS_MESSAGE = "Here are some project ideas based on your input:\n{answers}\nPlease choose one of the project ideas to get more in-depth information."
DETAILED_PLAN_MESSAGE = "Here is the detailed plan for the chosen project:\n{answers}\nFeel free to ask any additional questions or share any doubts you may have."

# In-memory storage for user data
user_data = {}

@app.route('/')
def serve_index():
    return render_template('index.html')

@app.route('/todo')
def serve_todo():
    return render_template('todo.html')

@app.route('/index')
def serve_index2():
    return render_template('index.html')

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_message = request.form.get('message')
        logging.debug(f"User message received: {user_message}")

        if user_message:
            response = handle_user_response(user_message)
        else:
            response = "Please provide a message."

        return render_template('index.html', user_message=user_message, bot_response=response, tasks=user_data.get('tasks', []))

    return render_template('index.html', user_message=None, bot_response=None, tasks=[])

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data.get('message').strip().lower()
        user_id = data.get('user_id')  # Assuming a unique user ID is provided

        if user_id not in user_data:
            user_data[user_id] = {'step': 0}

        if user_message in ["hi", "hello", "hey"] and user_data[user_id]['step'] == 0:
            user_data[user_id]['step'] = 1
            return jsonify({"response": WELCOME_MESSAGE})

        response_content = handle_user_response(user_id, user_message)
        return jsonify({"response": response_content})

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

def handle_user_response(user_id, user_message):
    try:
        context = user_data.get(user_id, {})
        step = context.get('step', 1)  # Ensure step starts at 1

        if step <= 9:  # Updated to include the new TIME_MESSAGE step
            response_content = get_current_question(step)

            relevance = check_relevance_sync(user_message, step)
            if relevance:
                update_user_data(user_id, step, user_message)
                user_data[user_id]['step'] = step + 1
                if step + 1 == 10:  # After collecting input, generate project ideas
                    generated_ideas = generate_project_ideas(user_data[user_id])
                    logging.debug(f"Generated Project Ideas: {generated_ideas}")
                    response_content = PROJECT_IDEAS_MESSAGE.replace("{answers}", generated_ideas)
                    user_data[user_id]['step'] = 10
                else:
                    response_content = get_current_question(step + 1)
            else:
                response_content = f"Your answer doesn't seem relevant to step {step}. Please try again."
        elif step == 10:
            # User has chosen a project idea
            chosen_project = user_message
            detailed_plan = get_in_depth_knowledge(user_data[user_id], chosen_project)
            response_content = DETAILED_PLAN_MESSAGE.replace("{answers}", detailed_plan)
            user_data[user_id]['step'] = 11

            # Generate and print the to-do list in the terminal
            todo_list = generate_todo_list(detailed_plan)
            logging.info("To-Do List:")
            for i, task in enumerate(todo_list, 1):
                logging.info(f"{i}. {task}")
        elif step == 11:
            # Route to the counselor function after step 11
            response_content = counselor(user_data[user_id])
        else:
            response_content = "Thank you! You've completed all the steps."  # This should never be reached now

        return response_content

    except Exception as e:
        logging.error(f"Error in handle_user_response: {e}")
        return "An error occurred while processing your request. Please try again."
    except Exception as e:
        logging.error(f"Error in handle_user_response: {e}")
        return "An error occurred while processing your request. Please try again."


def get_current_question(step):
    questions = {
        1: WELCOME_MESSAGE,
        2: BUDGET_MESSAGE,
        3: GROUP_SIZE_MESSAGE,
        4: PURPOSE_MESSAGE,
        5: DESCRIPTION_MESSAGE,
        6: LEVEL_MESSAGE,
        7: EDUCATION_LEVEL,
        8: TIME_MESSAGE,
        9: LOCATION_MESSAGE,
        10: PROJECT_IDEAS_MESSAGE ,
        11: DETAILED_PLAN_MESSAGE,
    }
    return questions.get(step, "I'm not sure how to assist with that.")

def check_relevance_sync(user_message, step):
    expected_context = {
        1: "SDG Goal: The user should provide a Sustainable Development Goal...",
        2: "Budget: The user should provide a numerical value...",
        3: "Group Size: The user should provide the number of people...",
        4: "Purpose: The user should describe their experience or reason...",
        5: "Project Description: The user should provide a detailed vision...",
        6: "Project Scope: The user should specify the project's scope by saying international or national or state or local",
        7: "Education Level: The user should mention their current level...",
        8: "Timeframe: the suer should provide a timeframe for the project...",
        9: "Project Location: The user should provide the specific location...",
        10: "Project Ideas: The user should choose one of the project ideas...",
        11: "In-depth Knowledge: The user should ask for further details..."
    }
    
    prompt = f"""
    Determine if the following message is relevant based on the context:\n\nMessage: {user_message}\nContext: {expected_context.get(step, 'General context')}\n\nIs this message relevant? (Yes/No)
    Allows if there are any typos and allows if they mean the correct thing but it doesnt come out that way 
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an AI that determines the relevance of user responses."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0
        )
        if response.choices and len(response.choices) > 0:
            relevance = response.choices[0].message['content'].strip().lower()
            logging.debug(f"Relevance check response: {relevance}")
            return relevance == "yes"
        else:
            logging.error("No response received from OpenAI API.")
            return False
    except Exception as e:
        logging.error(f"Error in relevance check with OpenAI: {e}")
        return False

def update_user_data(user_id, step, user_message):
    # Updating the user data based on step and message
    keys = {
        1: 'sdg_goal',
        2: 'budget',
        3: 'group_size',
        4: 'purpose',
        5: 'description',
        6: 'level',
        7: 'education',
        8: 'Timeframe',
        9: 'location'
    }
    key = keys.get(step)
    if key:
        user_data[user_id][key] = user_message

def generate_project_ideas(details):
    # Generate project ideas based on user details
    prompt = f"""
    SDG Goal: {details.get('sdg_goal', '')}
    Budget: {details.get('budget', '')}
    Group size: {details.get('group_size', '')}
    Purpose: {details.get('purpose', '')}
    Project description/specifications/requirements: {details.get('description', '')}
    Level: {details.get('level', '')}
    Location: {details.get('location', '')}
    Education: {details.get('education', '')}
    Timeframe: {details.get('Timeframe', '')}

     You also posses the knowledge of every succecful project invovling a SDG goal and use it to answer any question or doubt by the user on the project idea, project depth or doubts and queries overall and also give inspiration to the user by taking related project to their ideas as examples. So Generate 10 specific, very innovative, creative, and detailed project ideas taking into account the details above. For each project, include
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

     Take into consideration their budget and their timeframe along with the experience they have. Adjust the ideas according to their experience if it is their first project or some experince then diffeent ideas and if they are experinced then the ideas should more complex.

    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": ""},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.7
        )
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message['content'].strip()
        else:
            return "Sorry, I couldn't generate project ideas at this moment."
    except Exception as e:
        logging.error(f"Error in project ideas generation: {e}")
        return "Sorry, an error occurred while generating project ideas."

def get_in_depth_knowledge(details, chosen_project):
    # Generate a detailed plan based on the chosen project
    prompt = f"""
    Project Idea: {chosen_project}

    Based on the previously generated project ideas, particularly focusing on the project titled: "{chosen_project}", provide an in-depth, original, and convenient step-by-step guide for executing this project. 
    {user_data} use the user data to make the tailored fit answer. You have the knowledge and scale the projects on local, national and international levels and cater completely to the needs of the user. You also posses the knowledge of every succecful project invovling a SDG goal and use it to answer any question or doubt by the user on the project idea, project depth or doubts and queries overall and also give inspiration to the user by taking related project to their ideas as examples
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
      Make sure that all of these are fully put in the max token limit and none of the information is missed out 


    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert project planner."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.7
        )
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message['content'].strip()
        else:
            return "Sorry, I couldn't generate a detailed plan at this moment."
    except Exception as e:
        logging.error(f"Error in generating detailed plan: {e}")
        return "Sorry, an error occurred while generating the detailed plan."

def generate_todo_list(detailed_plan):
    # Extract a to-do list from the detailed plan
    prompt = f"""
    Detailed Plan: {detailed_plan}

    Extract the specific tasks and create a detailed to-do list from this plan.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a to-do list generator."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.7
        )
        if response.choices and len(response.choices) > 0:
            todo_list = response.choices[0].message['content'].strip().split("\n")
            return [task.strip() for task in todo_list if task.strip()]
        else:
            return ["Sorry, I couldn't generate a to-do list at this moment."]
    except Exception as e:
        logging.error(f"Error in generating to-do list: {e}")
        return ["Sorry, an error occurred while generating the to-do list."]
    
    
@app.route('/generate_todo_list', methods=['POST'])
def generate_todo_list_route():
    try:
        data = request.json
        user_id = data.get('user_id')  # Extract user_id from request

        if not user_id or user_id not in user_data:
            return jsonify({"error": "Invalid user ID"}), 400

        # Generate the to-do list based on the user data
        detailed_plan = get_in_depth_knowledge(user_data[user_id], "chosen_project")
        todo_list = generate_todo_list(detailed_plan)

        return jsonify({"tasks": todo_list})
    except Exception as e:
        logging.error(f"Error generating to-do list: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

def counselor(user_id, chosen_project):
    try:
        # Retrieve user data and the detailed plan for the chosen project
        user_details = user_data.get(user_id, {})
        detailed_plan = user_details.get('detailed_plan', '')
        
        # Combine user answers with the detailed plan for the chosen project
        combined_data = f"""
        User Details:
        SDG Goal: {user_details.get('sdg_goal', '')}
        Budget: {user_details.get('budget', '')}
        Group size: {user_details.get('group_size', '')}
        Purpose: {user_details.get('purpose', '')}
        Project description/specifications/requirements: {user_details.get('description', '')}
        Level: {user_details.get('level', '')}
        Location: {user_details.get('location', '')}
        Education: {user_details.get('education', '')}
        Timeframe: {user_details.get('timeframe', '')}

        Chosen Project: {chosen_project}
        
        Detailed Plan:
        {detailed_plan}

        Based on this combined data, please provide tailored advice and guidance...
        Provide a well-researched, insightful, and detailed response that addresses the user's question thoroughly, taking into account the context provided so far. Ensure that the advice is actionable and relevant to their current project. Consider any challenges they may face and offer solutions or alternative approaches. If necessary, refer to similar projects or examples to support your advice.

        """
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert counselor providing tailored advice based on project details and user-specific information."},
                {"role": "user", "content": combined_data}
            ],
            max_tokens=3000,
            temperature=0.7
        )

        if response.choices and len(response.choices) > 0:
            return response.choices[0].message['content'].strip()
        else:
            return "Sorry, I couldn't generate advice at this moment."
    except Exception as e:
        logging.error(f"Error in counselor function: {e}")
        return "Sorry, an error occurred while generating the advice."

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5004)