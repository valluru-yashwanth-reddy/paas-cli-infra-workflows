import click
import boto3
import git
import os
import uuid
import shutil
import subprocess
import requests
import json
import time
import random
import threading
from botocore.exceptions import ClientError
from datetime import datetime

# https://github.com/akhilesh-minfy/PortfolioReact
UPLOADS_BUCKET_NAME = "testbucketserviceminfy"
TEMPLATE_S3_PATH = f"s3://{UPLOADS_BUCKET_NAME}/templates/"
GITHUB_REPO = "valluru-yashwanth-reddy/paas-cli-infra-workflows"
WORKFLOW_FILE_NAME = "deploy-tool.yml"



QUOTES = [
    "Building your app... it's like watching paint dry, but with more coffee.",
    "Compiling... please wait. Or don't. I'm a script, not a cop.",
    "Just brewing some coffee. And by coffee, I mean your code.",
    "Reticulating splines... I have no idea what that means either.",
    "Uploading files. If this fails, we'll just blame the network. Deal?",
    "Building your app. It's not rocket science... but it's close.",
    "Hang tight, we're teaching the hamsters to run faster.",
]
ROASTS = [
    "This build is taking longer than my last relationship.",
    "If I had a dollar for every time this build failed, I'd be rich enough to buy a faster computer.",
    "Still watching? Don't you have code to write?",
    "Is this your first time using a command line? It's cute.",
    "I've seen faster builds. From a potato. A very slow potato.",
    "Your repo is so big, it has its own area code.",
    "Hope you didn't leave any console.logs in there. Or did you?",
    "Are you sure this is the right repository? Just checking.",
]

def remove_readonly(func, path, _):
    """Error handler for shutil.rmtree. Clears the readonly bit and retries the removal on Windows."""
    os.chmod(path, 0o666)
    func(path)

@click.group()
def cli():
    """A Vercel-like deployment CLI."""
    pass

def build_and_upload_worker(user_id, repo_url, build_dir, project_id, local_dir, result_list):
    """This function runs in a separate thread to handle the heavy lifting."""
    try:
        git.Repo.clone_from(repo_url, local_dir)
        
        # --- Auto-detect project path ---
        project_path = local_dir
        if not os.path.exists(os.path.join(local_dir, 'package.json')):
            found_projects = []
            for root, dirs, files in os.walk(local_dir):
                if '.git' in dirs:
                    dirs.remove('.git') 
                if 'node_modules' in dirs:
                    dirs.remove('node_modules')
                if 'package.json' in files:
                    found_projects.append(root)
            
            if not found_projects:
                raise FileNotFoundError("Could not find a 'package.json' in the root or any sub-directory.")
            if len(found_projects) > 1:
                raise Exception(f"Multiple projects found: {', '.join(os.path.relpath(p, local_dir) for p in found_projects)}. Please use a repo with a single project.")
            project_path = found_projects[0]
            click.echo(f"--> Project found in sub-directory: {os.path.relpath(project_path, local_dir)}")

        
        subprocess.run(["npm", "install", "--legacy-peer-deps"], cwd=project_path, check=True, shell=True, capture_output=True)
        subprocess.run(["npm", "run", "build"], cwd=project_path, check=True, shell=True, capture_output=True)
        upload_dir = os.path.join(project_path, build_dir)
        if not os.path.isdir(upload_dir):
            raise FileNotFoundError(f"Build directory '{build_dir}' not found inside '{os.path.relpath(project_path, local_dir)}'.")

        s3 = boto3.client(
            's3', region_name='ap-south-1',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            aws_session_token=AWS_SESSION_TOKEN
        )
        for root, _, files in os.walk(upload_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, upload_dir)
                s3_key = f"{user_id}/{project_id}/latest/{relative_path.replace('\\', '/')}"
                s3.upload_file(local_path, UPLOADS_BUCKET_NAME, s3_key)

        config = {
            "user_id": user_id,
            "project_id": project_id,
            "template_s3_path": TEMPLATE_S3_PATH,
            "instance_type": "t2.micro",
            "allowed_cidr": "0.0.0.0/0"
        }
        with open("deploy_config.json", 'w') as f:
            json.dump(config, f, indent=2)
            
    except Exception as e:
        result_list.append(e)

@cli.command()
def init():
    """Clones a repo, builds it, uploads files to S3, and saves a config."""
    user_id = click.prompt("Enter your user ID")
    repo_url = click.prompt("Enter the GitHub repository URL").strip()
    build_dir = click.prompt("Enter the project's build directory", default="build")
    project_id = str(uuid.uuid4())
    
    click.echo("\n Woah! Getting your application ready... This might take a few moments. ")
    local_dir = os.path.join(os.getcwd(), f"temp_clone_{project_id}")
    
    result = []
    worker_thread = threading.Thread(
        target=build_and_upload_worker,
        args=(user_id, repo_url, build_dir, project_id, local_dir, result)
    )

    try:
        worker_thread.start()
        is_roast_turn = False
        while worker_thread.is_alive():
            time.sleep(5)
            message = random.choice(ROASTS) if is_roast_turn else random.choice(QUOTES)
            icon = "HEY MAMA I CHITTI THE ROBOT ," if is_roast_turn else "I AM JAGAN MAMAYYA !"
            click.echo(f"  {icon} {message}")
            is_roast_turn = not is_roast_turn
        
        worker_thread.join()
        
        if result:
            raise result[0]

        click.echo("\n Woah! All set! Run 'deploy tool' to launch your application and see it live.")

    except subprocess.CalledProcessError as e:
        click.echo(f"\n OOPS ! Error during the build process. Please check the repository and try again.", err=True)
        click.echo(f"Error details: {e.stderr.decode() if e.stderr else 'No error output.'}", err=True)
    except Exception as e:
        click.echo(f"\n An error occurred: {e}", err=True)
    finally:
        if os.path.exists(local_dir):
            shutil.rmtree(local_dir, onerror=remove_readonly)

@cli.command()
@click.option('--config', default='deploy_config.json', help='Path to your deployment config file.')
def tool(config):
    """Triggers GitHub Actions, waits for completion, and shows the output IPs."""
    if not os.path.exists(config):
        click.echo(f"Error: Config file '{config}' not found. Run 'init' first.", err=True)
        return

    with open(config, 'r') as f:
        config_data = json.load(f)
    user_id = config_data["user_id"]
    project_id = config_data["project_id"]

    try:
        click.echo(f" Yeah we are triggering deployment for project: {project_id}")
        dispatch_url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
        headers = {"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
        
        payload = {
            "event_type": "deploy-tool",
            "client_payload": {
                "user_id": user_id,
                "project_id": project_id,
                "template_s3_path": config_data.get("template_s3_path"),
                "instance_type": config_data.get("instance_type", "t2.micro"),
                "allowed_cidr": config_data.get("allowed_cidr", "0.0.0.0/0")
            }
        }
        
        response = requests.post(dispatch_url, json=payload, headers=headers)
        if response.status_code != 204:
            raise Exception(f"Failed to trigger GitHub Actions: {response.text}")
        
        click.echo("Workflow triggered. Waiting for completion (this may take several minutes)...")

        time.sleep(20)
        for i in range(60):
            runs_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE_NAME}/runs"
            runs_response = requests.get(runs_url, headers=headers)
            runs_response.raise_for_status()
            latest_run = runs_response.json()["workflow_runs"][0]
            
            status = latest_run["status"]
            click.echo(f"--> Deployment status: {status}")

            if status == "completed":
                if latest_run["conclusion"] == "success":
                    click.echo("woah That's Cool !Workflow completed successfully!")
                    break
                else:
                    raise Exception(f" Oops !Workflow failed. See details: {latest_run['html_url']}")
            time.sleep(10)
        else:
            raise Exception("Timed out waiting for workflow completion.")

        click.echo("\nFetching deployment outputs...")
        stack_name = f"deploy-{user_id}-{project_id}"
        cf_client = boto3.client(
            'cloudformation',
            region_name='ap-south-1',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            aws_session_token=AWS_SESSION_TOKEN
        )
        response = cf_client.describe_stacks(StackName=stack_name)
        outputs = {o["OutputKey"]: o["OutputValue"] for o in response["Stacks"][0]["Outputs"]}

        click.echo("\n---  Deployment Complete ---")
        click.echo(f"Application URL: {outputs.get('ApplicationURL', 'Not found')}")
        click.echo(f"Monitor Your Application! Here is your Grafana URL: {outputs.get('GrafanaURL', 'Not found')}")

    except Exception as e:
        click.echo(f"\n An error occurred: {e}", err=True)

if __name__ == '__main__':
    cli()
