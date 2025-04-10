# Copyright (c) 2025 EPAM Systems

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import requests
import time
import traceback
from datetime import datetime, timezone
from github import Github, GithubException
from gitrepomanager.common.logging_utils import log_message
from gitrepomanager.common.logging_utils import LogLevel


def authenticate_to_github(*, access_token, enterprise_url=None):
    try:
        if enterprise_url:
            github_object = Github(
                base_url=f"{enterprise_url}/api/v3", login_or_token=access_token
            )
        else:  # github.com
            github_object = Github(access_token)
        return github_object
    except GithubException as e:
        raise (f"An error occurred while authenticating to GitHub: {e}")


def create_or_update_github_webhook(
    *,
    github_repo,
    webhook_config,
    indent_level=0,
):
    """
    Create or update a webhook on a repository.

    Args:
        github_repo: The repository object.
        webhook_config: A dictionary containing the webhook configuration. Expected keys:
            - url: The URL for the webhook.
            - events: A list of events the webhook should trigger on (default: ["push"]).
            - secret: The secret for the webhook (optional).
            - content_type: The content type for the webhook payload (default: "json").
            - insecure_ssl: Whether to allow insecure SSL (default: "0").
            - active: Whether the webhook should be active (default: True).
        indent_level: The indentation level for logging.

    Returns:
        The created or updated webhook object, or None if an error occurs.
    """
    try:
        url = webhook_config.get("url")
        if not url:
            raise ValueError("Webhook configuration must include a 'url' key.")

        active = webhook_config.get("active", True)
        content_type = webhook_config.get("content_type", "json")
        events = webhook_config.get("events", ["push"])
        insecure_ssl = webhook_config.get("insecure_ssl", "0")
        name = "web"  # only value accepted by github api
        secret = webhook_config.get("secret")

        # Check if a webhook with the same URL already exists
        existing_hooks = github_repo.get_hooks()
        for hook in existing_hooks:
            if hook.config.get("url") == url:
                # Update the existing webhook if necessary
                hook.edit(
                    name=name,
                    config={
                        "url": url,
                        "content_type": content_type,
                        "secret": secret,
                        "insecure_ssl": insecure_ssl,
                    },
                    events=events,
                    active=active,
                )
                log_message(
                    LogLevel.INFO,
                    f"Updated existing webhook for URL '{url}' on repository '{github_repo.full_name}'",
                    indent_level=indent_level,
                )
                return hook

        # Create a new webhook if no existing one matches
        new_hook = github_repo.create_hook(
            name=name,
            config={
                "url": url,
                "content_type": content_type,
                "secret": secret,
                "insecure_ssl": insecure_ssl,
            },
            events=events,
            active=active,
        )
        log_message(
            LogLevel.INFO,
            f"Created new webhook for URL '{url}' on repository '{github_repo.full_name}'",
            indent_level=indent_level,
        )
        return new_hook

    except GithubException as e:
        log_message(
            LogLevel.ERROR,
            f"Failed to create or update webhook for URL '{url}' on repository '{github_repo.full_name}': {e}",
            indent_level=indent_level,
        )
        return None


def get_github_info(*, github_target, github_user_login=None, indent_level=0):
    if not github_user_login:
        github_user_login = github_target.get_user().login
    log_message(LogLevel.INFO, "GitHub information:", indent_level=indent_level)
    log_message(
        LogLevel.INFO,
        "GitHub user: {}",
        github_user_login,
        indent_level=indent_level + 1,
    )
    return github_user_login


def get_github_repo_owner_type_plan(*, github_target, repo_owner, repo_name):
    try:
        repo = github_target.get_repo(f"{repo_owner}/{repo_name}")
        if repo.owner.type.lower() == "organization":
            type = "organization"
            org = github_target.get_organization(repo_owner)
            plan = org.plan.name  # e.g. "free", "team", "enterprise"
            return type, plan
        else:
            type = "user"
            return type, None
    except GithubException as e:
        log_message(
            LogLevel.ERROR, f"Failed to get GitHub repo owner plan: {e}", indent_level=1
        )
        return None


def get_github_repo_url(*, github_target, repo_name, repo_owner, indent_level=0):
    try:
        repo = github_target.get_repo(f"{repo_owner}/{repo_name}")
        repo_url = repo.clone_url
        log_message(
            LogLevel.DEBUG,
            f"Repository URL for '{repo_owner}/{repo_name}' is '{repo_url}'",
            indent_level=indent_level,
        )
        return repo_url
    except Exception as e:
        log_message(
            LogLevel.ERROR,
            f"Failed to get repository URL for '{repo_owner}/{repo_name}': {e}",
            indent_level=indent_level + 1,
        )
        return None


def get_github_user_plan(*, github_target):
    try:
        user = github_target.get_user()
        plan = user.plan.name
        log_message(LogLevel.DEBUG, f"GitHub plan: {plan}", indent_level=1)
        return plan
    except GithubException as e:
        log_message(LogLevel.ERROR, f"Failed to get GitHub plan: {e}", indent_level=1)
        return None


def get_github_version(*, github_target):
    try:
        requester = github_target._Github__requester
        headers, data = requester.requestJsonAndCheck("GET", "/meta")
        if "installed_version" in data:
            return data["installed_version"]
        else:
            return "unknown"
    except GithubException as e:
        log_message(LogLevel.ERROR, "Failed to get GitHub version: {}", e)
        return None


# def get_pygithub_version():
#     """
#     Get the version of PyGithub installed.

#     Returns:
#         str: The version of PyGithub.
#     """
#     try:
#         import pkg_resources

#         pygithub_version = pkg_resources.get_distribution("PyGithub").version
#         return pygithub_version
#     except Exception as e:
#         log_message(LogLevel.ERROR, "Failed to get PyGithub version: {}", e)
#         return None


def github_check_rate_limit(*, github_target, indent_level=0):
    try:
        rate_limit = github_target.get_rate_limit()
        core_rate_limit = rate_limit.core
        # Check if the remaining limit is below a threshold
        percent_remaining = round(
            100 * core_rate_limit.remaining / core_rate_limit.limit
        )
        time_remaining = round(
            (
                core_rate_limit.reset.astimezone(timezone.utc)
                - datetime.now(timezone.utc)
            ).total_seconds()
        )
        log_message(
            LogLevel.DEBUG,
            "GitHub rate limit: {}% remaining, {} seconds until reset",
            percent_remaining,
            time_remaining,
            indent_level=indent_level,
        )
        # backoff if we are below a threshold
        threshold = 30
        if percent_remaining <= threshold:
            sleep_time = (
                time_remaining * (threshold - percent_remaining + 1) / threshold
            )
            # examples of this calculation for threshold=30
            #   percent_remaining = 30, sleep for   3% of the time remaining
            #   percent_remaining = 25, sleep for  20% of the time remaining
            #   percent_remaining = 15, sleep for  53% of the time remaining
            #   percent_remaining = 5,  sleep for  87% of the time remaining
            #   percent_remaining = 2,  sleep for  97% of the time remaining
            #   percent_remaining = 1,  sleep for 100% of the time remaining
            log_message(
                LogLevel.WARNING,
                "Approaching GitHub rate limit. Sleeping for {} seconds.",
                sleep_time,
                indent_level=indent_level,
            )
            time.sleep(sleep_time)

    except GithubException as e:
        log_message(
            LogLevel.CRITICAL, "An error occurred: {}", e, indent_level=indent_level
        )


def github_create_repo(
    *,
    github_target,
    repo_name,
    org_name=None,
    expected_settings={},
    indent_level=0,
    dry_run=False,
):
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                (
                    f"[Dry-run] Would create repository '{repo_name}' in organization '{org_name}'"
                    if org_name
                    else f"[Dry-run] Would create user repository '{repo_name}'"
                ),
                indent_level=indent_level,
            )
            return None  # Simulate no repo created
        # use a minimal set of settings to create the repo
        # so make sure that enforce_repo_settings() will be run shortly afterwards
        repo_settings = {
            "name": repo_name,
            "private": expected_settings.get("private", True),
            "auto_init": expected_settings.get("auto_init", False),
        }
        if org_name:
            # Create a repository in the specified organization
            org = github_target.get_organization(org_name)
            new_repo = org.create_repo(**repo_settings)
            log_message(
                LogLevel.INFO,
                f"Repository '{repo_name}' created in organization '{org_name}'",
                indent_level=indent_level,
            )
        else:
            # Create a user repository
            new_repo = github_target.get_user().create_repo(**repo_settings)
            log_message(
                LogLevel.INFO,
                f"User repository '{repo_name}' created for user",
                indent_level=indent_level,
            )

        return new_repo

    except GithubException as e:
        raise Exception("An error occurred while creating repo: {}", e)


def github_enforce_branch_protection(
    *,
    github_repo,
    repo_name,
    repo_owner,
    expected_settings,
    indent_level=0,
    dry_run=False,
    remove_unwanted=False,
    github_token=None,
):
    """
    Enforce branch protection rules for a GitHub repository.


    Args:
        github_repo (object): The GitHub repository object.
        repo_name (str): The name of the repository.
        repo_owner (str): The owner of the repository.
        expected_settings (dict): The expected settings containing branch protection rules.
        indent_level (int): The indentation level for logging.
        dry_run (bool): If True, simulate the changes without applying them.
        remove_unwanted (bool): If True, remove branch protections and rules not in the expected settings.
        github_token (str): The GitHub personal access token for authentication.

    Returns:
        None
    """
    try:
        branch_protection_data = expected_settings.get("branch_protection", {})
        if not branch_protection_data:
            log_message(
                LogLevel.INFO,
                f"No branch protection settings found for repository '{repo_name}'. Skipping branch protection enforcement.",
                indent_level=indent_level,
            )
            return

        # Enforce expected branch protections
        for protection_name, protection_settings in branch_protection_data.items():
            branches = protection_settings.get("branches", ["main"])
            protections = protection_settings.get("protections", {})

            for branch_name in branches:
                log_message(
                    LogLevel.INFO,
                    f"Enforcing branch protection '{protection_name}' for branch '{branch_name}' in repository '{repo_name}'.",
                    indent_level=indent_level,
                )

                if dry_run:
                    log_message(
                        LogLevel.INFO,
                        f"[Dry-run] Would enforce branch protection '{protection_name}' for branch '{branch_name}' in repository '{repo_name}'.",
                        indent_level=indent_level,
                    )
                    continue

                try:
                    branch = github_repo.get_branch(branch_name)
                    log_message(
                        LogLevel.DEBUG,
                        f"Retrieved branch '{branch_name}' for repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
                except GithubException as e:
                    if e.status == 404:
                        log_message(
                            LogLevel.WARNING,
                            f"Branch '{branch_name}' does not exist in repository '{repo_name}'. Skipping branch protection enforcement.",
                            indent_level=indent_level,
                        )
                        continue
                    else:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to retrieve branch '{branch_name}' in repository '{repo_name}': {e}",
                            indent_level=indent_level,
                        )
                        raise

                # Apply branch protection rules with safe handling for missing elements
                log_message(
                    LogLevel.DEBUG,
                    f"Applying branch protection rules for branch '{branch_name}' in repository '{repo_name}'.",
                    indent_level=indent_level + 1,
                )

                # Convert the entire protections dictionary to JSON and use the GitHub API to set branch protection
                import json

                repo_api_url = github_repo.url
                headers = {"Authorization": f"Bearer {github_token}"}
                branch_protection_url = (
                    f"{repo_api_url}/branches/{branch_name}/protection"
                )

                try:
                    protections_json = json.dumps(
                        protections
                    )  # Convert entire protections to JSON
                    response = requests.put(
                        branch_protection_url,
                        headers=headers,
                        data=protections_json,  # Use the JSON string directly
                    )
                    if response.status_code == 200:
                        log_message(
                            LogLevel.INFO,
                            f"Branch protection set successfully for branch '{branch_name}' in repository '{repo_name}'.",
                            indent_level=indent_level + 1,
                        )
                    else:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to set branch protection for branch '{branch_name}' in repository '{repo_name}': {response.text}",
                            indent_level=indent_level + 1,
                        )
                except Exception as e:
                    log_message(
                        LogLevel.ERROR,
                        f"An error occurred while setting branch protection for branch '{branch_name}' in repository '{repo_name}': {e}",
                        indent_level=indent_level + 1,
                    )

        # Remove unwanted branch protections if enabled
        if remove_unwanted:
            log_message(
                LogLevel.INFO,
                f"Checking for unwanted branch protections in repository '{repo_name}' using GraphQL API.",
                indent_level=indent_level + 1,
            )
            try:
                api_url = github_repo.url.split("/repos")[0]
                # Use GraphQL API to fetch all branch protection rules
                query = """
                query($owner: String!, $repo: String!) {
                    repository(owner: $owner, name: $repo) {
                        branchProtectionRules(first: 100) {
                            nodes {
                                id
                                pattern
                            }
                        }
                    }
                }
                """
                variables = {"owner": repo_owner, "repo": repo_name}
                headers = {
                    "Authorization": f"Bearer {github_token}"
                }  # Use github_token

                response = requests.post(
                    f"{api_url}/graphql",
                    json={"query": query, "variables": variables},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                branch_protection_rules = data["data"]["repository"][
                    "branchProtectionRules"
                ]["nodes"]
                # Flatten the list of branches and construct the expected_patterns set
                expected_patterns = set(
                    branch
                    for protection_settings in branch_protection_data.values()
                    for branch in protection_settings.get("branches", ["main"])
                )

                for rule in branch_protection_rules:
                    if rule["pattern"] not in expected_patterns:
                        log_message(
                            LogLevel.INFO,
                            f"Removing unwanted branch protection rule with pattern '{rule['pattern']}' in repository '{repo_name}'.",
                            indent_level=indent_level + 1,
                        )
                        if not dry_run:
                            api_url = github_repo.url.split("/repos")[0]
                            delete_mutation = """
                            mutation($id: ID!) {
                                deleteBranchProtectionRule(input: {branchProtectionRuleId: $id}) {
                                    clientMutationId
                                }
                            }
                            """
                            delete_variables = {"id": rule["id"]}
                            delete_response = requests.post(
                                f"{api_url}/graphql",
                                json={
                                    "query": delete_mutation,
                                    "variables": delete_variables,
                                },
                                headers=headers,
                            )
                            delete_response.raise_for_status()
            except Exception as e:
                log_message(
                    LogLevel.ERROR,
                    f"Failed to remove unwanted branch protections for repository '{repo_name}': {e}",
                    indent_level=indent_level,
                )
                raise

    except Exception as e:
        log_message(
            LogLevel.ERROR,
            f"Failed to enforce branch protection for repository '{repo_name}': {e}",
            indent_level=indent_level,
        )
        raise


def github_enforce_gitignore(
    *,
    github_repo,
    repo_name,
    repo_owner,
    expected_settings,
    indent_level=0,
    dry_run=False,
    config_directory=None,
):
    """
    Enforce the .gitignore configuration for a GitHub repository.

    Args:
        github_repo (object): The GitHub repository object.
        expected_settings (dict): The expected settings containing .gitignore configuration and branches.
        indent_level (int): The indentation level for logging.
    """
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce .gitignore for repository '{repo_name}'",
                indent_level=indent_level,
            )
            return
        gitignore_data = expected_settings.get("gitignore", None)
        if not gitignore_data:
            log_message(
                LogLevel.DEBUG,
                f"No .gitignore settings found for repository '{repo_name}'. Skipping .gitignore enforcement.",
                indent_level=indent_level,
            )
            return

        gitignore_config = gitignore_data.get("config")
        if not gitignore_config:
            log_message(
                LogLevel.ERROR,
                f"gitignore mentioned but config missing for repository '{repo_name}'.",
                indent_level=indent_level,
            )
            return
        gitignore_type = gitignore_data.get("type", "file")
        branches = gitignore_data.get("branches", ["main"])

        log_message(
            LogLevel.INFO,
            f"Enforcing .gitignore for repository '{repo_name}' on branches: {branches}",
            indent_level=indent_level,
        )

        # Use the type provided in the gitignore data
        if gitignore_type == "url":
            # Fetch .gitignore content from URL
            log_message(
                LogLevel.INFO,
                f"Fetching .gitignore content from URL: {gitignore_config}",
                indent_level=indent_level + 1,
            )
            response = requests.get(gitignore_config)
            response.raise_for_status()
            gitignore_content = response.text
        elif gitignore_type == "file":
            # Read .gitignore content from file, which must be relative to config_directory
            log_message(
                LogLevel.INFO,
                f"Reading .gitignore content from file: {gitignore_config}",
                indent_level=indent_level + 1,
            )
            with open(os.path.join(config_directory, gitignore_config), "r") as file:
                gitignore_content = file.read()
        elif gitignore_type == "list":
            # Use inline list as .gitignore content
            log_message(
                LogLevel.INFO,
                "Using inline .gitignore content.",
                indent_level=indent_level + 1,
            )
            gitignore_content = "\n".join(gitignore_config)
        else:
            raise ValueError(f"Unsupported .gitignore type: {gitignore_type}")

        # Apply the .gitignore content to the specified branches
        for branch in branches:
            log_message(
                LogLevel.INFO,
                f"Checking .gitignore for branch '{branch}' in repository '{repo_name}'.",
                indent_level=indent_level + 1,
            )
            try:
                contents = github_repo.get_contents(".gitignore", ref=branch)
                current_content = contents.decoded_content.decode("utf-8")
                if current_content != gitignore_content:
                    log_message(
                        LogLevel.INFO,
                        f"Updating .gitignore for branch '{branch}' in repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
                    github_repo.update_file(
                        path=contents.path,
                        message=f"Update .gitignore on branch '{branch}'",
                        content=gitignore_content,
                        sha=contents.sha,
                        branch=branch,
                    )
                else:
                    log_message(
                        LogLevel.INFO,
                        f".gitignore is already up-to-date for branch '{branch}' in repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
            except GithubException as e:
                if e.status == 404:
                    # File does not exist, create it
                    log_message(
                        LogLevel.INFO,
                        f"Creating .gitignore for branch '{branch}' in repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
                    github_repo.create_file(
                        path=".gitignore",
                        message=f"Create .gitignore on branch '{branch}'",
                        content=gitignore_content,
                        branch=branch,
                    )
                else:
                    raise

        log_message(
            LogLevel.INFO,
            f".gitignore enforcement completed for repository '{github_repo.full_name}'.",
            indent_level=indent_level,
        )
    except Exception as e:
        log_message(
            LogLevel.ERROR,
            f"Failed to enforce .gitignore for repository '{github_repo.full_name}': {e}",
            indent_level=indent_level,
        )
        raise


def github_enforce_codeowners(
    *,
    github_repo,
    repo_name,
    repo_owner,
    expected_settings,
    indent_level=0,
    dry_run=False,
):
    """
    Enforce the CODEOWNERS file configuration for a GitHub repository.

    Args:
        github_repo (object): The GitHub repository object.
        expected_settings (dict): The expected settings containing CODEOWNERS configuration.
        indent_level (int): The indentation level for logging.
    """
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce CODEOWNERS for repository '{repo_name}'",
                indent_level=indent_level,
            )
            return

        codeowners_data = expected_settings.get("codeowners", None)
        if not codeowners_data:
            log_message(
                LogLevel.INFO,
                f"No CODEOWNERS settings found for repository '{repo_name}'. Skipping CODEOWNERS enforcement.",
                indent_level=indent_level,
            )
            return

        # Extract branches and config from the CODEOWNERS data
        branches = codeowners_data.get("branches", ["main"])
        config = codeowners_data.get("config", [])
        if not isinstance(config, list):
            raise ValueError(
                f"Unsupported CODEOWNERS configuration type for repository '{repo_name}'. Only inline lists are supported."
            )

        codeowners_content = "\n".join(config)

        log_message(
            LogLevel.INFO,
            f"Enforcing CODEOWNERS for repository '{repo_name}' on branches: {branches}",
            indent_level=indent_level,
        )

        # Apply the CODEOWNERS content to the specified branches
        for branch in branches:
            try:
                contents = github_repo.get_contents("CODEOWNERS", ref=branch)
                current_content = contents.decoded_content.decode("utf-8")
                if current_content != codeowners_content:
                    log_message(
                        LogLevel.INFO,
                        f"Updating CODEOWNERS for branch '{branch}' in repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
                    if not dry_run:
                        github_repo.update_file(
                            path=contents.path,
                            message=f"Update CODEOWNERS file on branch '{branch}'",
                            content=codeowners_content,
                            sha=contents.sha,
                            branch=branch,
                        )
                else:
                    log_message(
                        LogLevel.INFO,
                        f"CODEOWNERS is already up-to-date for branch '{branch}' in repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
            except GithubException as e:
                if e.status == 404:
                    # File does not exist, create it
                    log_message(
                        LogLevel.INFO,
                        f"Creating CODEOWNERS for branch '{branch}' in repository '{repo_name}'.",
                        indent_level=indent_level + 1,
                    )
                    if not dry_run:
                        github_repo.create_file(
                            path="CODEOWNERS",
                            message=f"Create CODEOWNERS file on branch '{branch}'",
                            content=codeowners_content,
                            branch=branch,
                        )
                else:
                    raise

        log_message(
            LogLevel.INFO,
            f"CODEOWNERS enforcement completed for repository '{repo_name}'.",
            indent_level=indent_level,
        )
    except Exception as e:
        log_message(
            LogLevel.ERROR,
            f"Failed to enforce CODEOWNERS for repository '{repo_name}': {e}",
            indent_level=indent_level,
        )
        raise


def github_enforce_repo_settings(
    *,
    github_repo,
    expected_settings,
    reponame,
    repoowner,
    indent_level=0,
    dry_run=False,
    remove_unwanted=False,
):
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce settings for {repoowner}/{reponame}",
                indent_level=indent_level,
            )
            return True  # Simulate success
        log_message(
            LogLevel.INFO,
            f"Repository settings enforcing for {repoowner}/{reponame}",
            indent_level=indent_level,
        )
        # List of attributes to check
        attributes = [
            "allow_merge_commit",
            "allow_rebase_merge",
            "allow_squash_merge",
            "default_branch",
            "delete_branch_on_merge",
            "has_discussions",
            "has_issues",
            "has_projects",
            "has_wiki",
            "private",
        ]

        # Get current settings dynamically
        current_settings = {
            attr: github_repo.__dict__.get(attr, None)
            for attr in attributes
            if attr in github_repo.__dict__
        }

        # Check if the repository has any branches
        branches = list(github_repo.get_branches())
        if not branches:
            log_message(
                LogLevel.WARNING,
                f"Repository {repoowner}/{reponame} has no branches. Skipping default_branch setting.",
                indent_level=indent_level,
            )
            current_settings.pop("default_branch", None)
            expected_settings.pop("default_branch", None)

        # Determine if settings need to be updated
        update_needed = any(
            current_settings[key] != expected_settings.get(key, current_settings[key])
            for key in current_settings
        )

        if update_needed:
            # Build the arguments for the edit method dynamically
            edit_args = {key: expected_settings.get(key) for key in current_settings}

            github_repo.edit(**edit_args)
            log_message(
                LogLevel.INFO,
                f"Repository settings enforced for {repoowner}/{reponame}",
                indent_level=indent_level,
            )
        else:
            log_message(
                LogLevel.INFO,
                f"Repository settings correct No changes needed for repository settings for {repoowner}/{reponame}",
                indent_level=indent_level,
            )
        return True
    except GithubException as e:
        raise Exception(
            f"Error while enforcing settings for repo {repoowner}/{reponame}: {e}"
        )


def github_enforce_repo_team_permissions(
    *,
    github_instance,
    repo_name,
    expected_repo_data,
    github_token,
    indent_level=0,
    dry_run=False,
    permissions_remove_unwanted_force_false=False,
):
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce team permissions for {repo_name}",
                indent_level=indent_level,
            )
            return  # Simulate no changes
        org_name = expected_repo_data.get("owner")
        log_message(
            LogLevel.INFO,
            f"Team permissions enforcing for {repo_name}",
            indent_level=indent_level,
        )
        # Get the repository object
        github_repo = github_instance.get_repo(f"{org_name}/{repo_name}")
        api_url = github_repo.url.split("/repos")[0]
        # Get the current team permissions from the repository
        current_permissions = {
            team.slug.lower(): team.permission for team in github_repo.get_teams()
        }
        desired_permissions = expected_repo_data.get("team_permissions", {})
        desired_permissions = {
            team_slug.lower(): permission
            for team_slug, permission in desired_permissions.items()
        }
        all_teams = set(current_permissions.keys()).union(desired_permissions.keys())
        # Determine if unwanted permissions should be removed
        permissions_remove_unwanted = expected_repo_data.get(
            "permissions_remove_unwanted", True
        )
        # Compare and enforce permissions
        for team in all_teams:
            desired_permission = desired_permissions.get(team, None)
            current_permission = current_permissions.get(team, None)
            # Ensure current_permission is a string
            if isinstance(current_permission, str):
                # Already a string, use it directly
                pass
            elif hasattr(current_permission, "admin"):
                # Handle older PyGithub versions where current_permission is a Permissions object
                if current_permission.admin:
                    current_permission = "admin"
                elif current_permission.push:
                    current_permission = "push"
                elif current_permission.pull:
                    current_permission = "pull"
                else:
                    current_permission = None  # Default if no permissions are set
            else:
                current_permission = None  # Fallback for unexpected cases

            permission_mapping = {"write": "push", "read": "pull"}
            current_permission = permission_mapping.get(
                current_permission, current_permission
            )
            desired_permission = permission_mapping.get(
                desired_permission, desired_permission
            )
            log_message(
                LogLevel.DEBUG,
                f"Normalised current team {team} permissions: {current_permission}",
                indent_level=indent_level + 2,
            )
            log_message(
                LogLevel.DEBUG,
                f"Normalised desired team {team} permissions: {desired_permission}",
                indent_level=indent_level + 2,
            )

            # Determine if an update is needed
            if desired_permission is None:
                # they have a permission they should not
                # need to remove
                if (
                    permissions_remove_unwanted
                    and not permissions_remove_unwanted_force_false
                ):
                    try:
                        org = github_repo.organization
                        org_team = org.get_team_by_slug(team)

                        # Use REST API to remove the team from the repository
                        api_url = github_repo.url.split("/repos")[0]
                        headers = {"Authorization": f"Bearer {github_token}"}
                        remove_team_url = f"{api_url}/orgs/{org.login}/teams/{team}/repos/{org.login}/{repo_name}"

                        response = requests.delete(remove_team_url, headers=headers)
                        if response.status_code == 204:
                            log_message(
                                LogLevel.INFO,
                                f"Removed team {team} from {repo_name} using API call",
                                indent_level=indent_level + 1,
                            )
                        elif response.status_code == 404:
                            log_message(
                                LogLevel.DEBUG,
                                f"Team {team} not found while attempting to remove it from {repo_name}. It may be a permission inherited from org.",
                                indent_level=indent_level + 1,
                            )
                        else:
                            log_message(
                                LogLevel.ERROR,
                                f"Failed to remove team {team} from {repo_name} using API call: {response.text}",
                                indent_level=indent_level + 1,
                            )
                    except GithubException as e:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to remove team {team} from {repo_name}: {e}",
                            indent_level=indent_level + 1,
                        )
                else:
                    log_message(
                        LogLevel.INFO,
                        f"Would have removed team {team} from {repo_name} but permissions_remove_unwanted={permissions_remove_unwanted} and permissions_remove_unwanted_force_false={permissions_remove_unwanted_force_false}",
                        indent_level=indent_level + 1,
                    )
                    log_message(
                        LogLevel.WARNING,
                        f"PERMISSIONCORRECTION:REMOVEREQUEST:{repo_name}:{team}:{current_permission}:{desired_permission}",
                        indent_level=indent_level + 1,
                    )
            else:
                # if there is a difference in permission, so add/update
                if (
                    current_permission is None
                    or current_permission != desired_permission
                ):
                    try:
                        # Check if the team exists
                        org = github_instance.get_organization(org_name)
                        team_obj = org.get_team_by_slug(team)
                    except GithubException as e:
                        log_message(
                            LogLevel.ERROR,
                            f"Team {team} requested as a collaborator to {repo_name}: team does not exist",
                            indent_level=indent_level + 1,
                        )
                        continue
                    if current_permission != desired_permission and (
                        not permissions_remove_unwanted
                        or permissions_remove_unwanted_force_false
                    ):
                        #  this could remove some permission unexpectedly
                        log_message(
                            LogLevel.INFO,
                            f"Will NOT change {team} from {current_permission} to {desired_permission} as permissions_remove_unwanted={permissions_remove_unwanted} and permissions_remove_unwanted_force_false={permissions_remove_unwanted_force_false}",
                            indent_level=indent_level + 1,
                        )
                        log_message(
                            LogLevel.WARNING,
                            f"PERMISSIONCORRECTION:CHANGEREQUEST:{repo_name}:{team}:{current_permission}:{desired_permission}",
                            indent_level=indent_level + 1,
                        )
                    else:
                        try:
                            team_obj.set_repo_permission(
                                github_repo, permission=desired_permission
                            )
                            log_message(
                                LogLevel.INFO,
                                f"Updated team {team} permission to {desired_permission} in {repo_name}",
                                indent_level=indent_level + 1,
                            )
                        except GithubException as e:
                            log_message(
                                LogLevel.ERROR,
                                f"Failed to update team {team}'s permission in {repo_name}: {e}",
                                indent_level=indent_level + 1,
                            )
                            continue

        log_message(
            LogLevel.INFO,
            f"Team permissions enforced for repository {repo_name}",
            indent_level=indent_level,
        )
    except GithubException as e:
        log_message(
            LogLevel.ERROR,
            f"Error while enforcing team permissions in repository {repo_name}: {e}",
            indent_level=indent_level,
        )


def github_enforce_repo_user_permissions(
    *,
    github_instance,
    repo_name,
    expected_repo_data,
    indent_level=0,
    dry_run=False,
    permissions_remove_unwanted_force_false=False,
):
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce user permissions for {repo_name}",
                indent_level=indent_level,
            )
            return  # Simulate no changes
        org_name = expected_repo_data.get("owner")
        log_message(
            LogLevel.INFO,
            f"User permissions enforcing for {repo_name}",
            indent_level=indent_level,
        )
        # Get the repository object
        repo = github_instance.get_repo(f"{org_name}/{repo_name}")
        # Get the current user permissions from the repository, only consider direct collaborators
        current_permissions = {
            collaborator.login: collaborator.permissions
            for collaborator in repo.get_collaborators(affiliation="direct")
        }
        # Get the desired user permissions from the repo_data
        desired_permissions = expected_repo_data.get("user_permissions", {})
        # Determine if unwanted permissions should be removed
        permissions_remove_unwanted = expected_repo_data.get(
            "permissions_remove_unwanted", True
        )
        # Combine current and expanded desired permissions to ensure all users are considered
        all_users = set(current_permissions.keys()).union(desired_permissions.keys())

        # Compare and enforce permissions
        for user in all_users:
            desired_permission = desired_permissions.get(user)
            current_permission = current_permissions.get(user, {})
            # Ensure current_permission is a string
            if isinstance(current_permission, str):
                # Already a string, use it directly
                pass
            elif hasattr(current_permission, "admin"):
                # Handle older PyGithub versions where current_permission is a Permissions object
                if current_permission.admin:
                    # note that if you are admin all the permissions are likely to be True, so check this one first
                    current_permission = "admin"
                elif current_permission.push:
                    current_permission = "push"
                elif current_permission.triage:
                    current_permission = "triage"
                elif current_permission.pull:
                    current_permission = "pull"
                else:
                    current_permission = None  # Default if no permissions are set
            else:
                current_permission = None  # Fallback for unexpected cases
            permission_mapping = {"write": "push", "read": "pull"}
            current_permission = permission_mapping.get(
                current_permission, current_permission
            )
            desired_permission = permission_mapping.get(
                desired_permission, desired_permission
            )
            log_message(
                LogLevel.DEBUG,
                f"User {user} permissions: {current_permission}",
                indent_level=indent_level + 1,
            )
            if desired_permission is None:
                if (
                    permissions_remove_unwanted
                    and not permissions_remove_unwanted_force_false
                ):
                    try:
                        repo.remove_from_collaborators(user)
                        log_message(
                            LogLevel.INFO,
                            f"Removed {user} from {repo_name}",
                            indent_level=indent_level,
                        )
                    except GithubException as e:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to remove {user} from {repo_name}: {e}",
                            indent_level=indent_level,
                        )
                else:
                    log_message(
                        LogLevel.INFO,
                        f"Would have removed user {user} from {repo_name} but permissions_remove_unwanted={permissions_remove_unwanted} and permissions_remove_unwanted_force_false={permissions_remove_unwanted_force_false}",
                        indent_level=indent_level,
                    )
            else:
                # if there is a difference in permission, so add/update
                if (
                    current_permission is None
                    or current_permission != desired_permission
                ):
                    try:
                        # Check if the user exists
                        github_instance.get_user(user)
                    except GithubException as e:
                        log_message(
                            LogLevel.ERROR,
                            f"User {user} requested as a collaborator to {repo_name} does not exist",
                            indent_level=indent_level + 1,
                        )
                        continue

                    try:
                        repo.add_to_collaborators(user, permission=desired_permission)
                        log_message(
                            LogLevel.INFO,
                            f"Updated {user}'s permission to {desired_permission} in {repo_name}",
                            indent_level=indent_level + 1,
                        )
                    except GithubException as e:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to add {user} as a collaborator to {repo_name}: {e}",
                            indent_level=indent_level + 1,
                        )
                        continue

        log_message(
            LogLevel.INFO,
            f"User permissions enforced for repository {repo_name}",
            indent_level=indent_level,
        )

    except GithubException as e:
        log_message(
            LogLevel.ERROR,
            f"Error while enforcing user permissions in repository {repo_name}: {e}",
            indent_level=indent_level,
        )


def github_enforce_repo_webhooks(
    *, github_repo, repo_name, expected_settings, indent_level=0, dry_run=False
):
    """
    Enforce the desired webhooks on a repository.

    Args:
        github_repo: The repository object.
        expected_settings: A list of desired webhook configurations.
        indent_level: The indentation level for logging.
        dry_run: If True, simulate the changes without applying them.

    Returns:
        None
    """
    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce webhooks for {repo_name}",
                indent_level=indent_level,
            )
            return  # Simulate no changes

        log_message(
            LogLevel.INFO,
            f"Enforcing webhooks for {github_repo.full_name}",
            indent_level=indent_level,
        )

        # Check if there are no webhooks in the expected settings
        if not expected_settings.get("webhooks"):
            log_message(
                LogLevel.INFO,
                f"No webhooks specified in expected settings for {repo_name}",
                indent_level=indent_level,
            )
            return

        # Get existing webhooks
        existing_hooks = github_repo.get_hooks()

        # Compare and enforce webhooks
        for desired_webhook in expected_settings["webhooks"]:
            url = desired_webhook.get("url")
            if not url:
                log_message(
                    LogLevel.WARNING,
                    "Skipping webhook with missing 'url' in expected settings.",
                    indent_level=indent_level,
                )
                continue

            # Check if a webhook with the same URL already exists
            matching_hook = next(
                (hook for hook in existing_hooks if hook.config.get("url") == url), None
            )

            if matching_hook:
                # Compare existing webhook configuration with the desired configuration
                existing_config = {
                    "url": matching_hook.config.get("url"),
                    "content_type": matching_hook.config.get("content_type", "json"),
                    "secret": matching_hook.config.get("secret"),
                    "insecure_ssl": matching_hook.config.get("insecure_ssl", "0"),
                }
                desired_config = {
                    "url": desired_webhook.get("url"),
                    "content_type": desired_webhook.get("content_type", "json"),
                    "secret": desired_webhook.get("secret"),
                    "insecure_ssl": desired_webhook.get("insecure_ssl", "0"),
                }

                if (
                    existing_config != desired_config
                    or set(matching_hook.events)
                    != set(desired_webhook.get("events", ["push"]))
                    or matching_hook.active != desired_webhook.get("active", True)
                ):
                    log_message(
                        LogLevel.INFO,
                        f"Updating webhook for URL '{url}' on repository '{repo_name}'",
                        indent_level=indent_level + 1,
                    )
                    if not dry_run:
                        matching_hook.edit(
                            name="web",
                            config=desired_config,
                            events=desired_webhook.get("events", ["push"]),
                            active=desired_webhook.get("active", True),
                        )
                else:
                    log_message(
                        LogLevel.INFO,
                        f"Webhook for URL '{url}' is already up-to-date on repository '{repo_name}'",
                        indent_level=indent_level + 1,
                    )
            else:
                # Create a new webhook if no existing one matches
                log_message(
                    LogLevel.INFO,
                    f"Creating new webhook for URL '{url}' on repository '{repo_name}'",
                    indent_level=indent_level + 1,
                )
                if not dry_run:
                    github_repo.create_hook(
                        name="web",
                        config={
                            "url": desired_webhook.get("url"),
                            "content_type": desired_webhook.get("content_type", "json"),
                            "secret": desired_webhook.get("secret"),
                            "insecure_ssl": desired_webhook.get("insecure_ssl", "0"),
                        },
                        events=desired_webhook.get("events", ["push"]),
                        active=desired_webhook.get("active", True),
                    )

        log_message(
            LogLevel.INFO,
            f"Webhooks enforced for repository {repo_name}",
            indent_level=indent_level,
        )
    except GithubException as e:
        log_message(
            LogLevel.ERROR,
            f"Error while enforcing webhooks in repository {repo_name}: {e}",
            indent_level=indent_level,
        )


def github_enforce_rulesets(
    *,
    github_repo,
    expected_settings,
    github_token,
    indent_level=0,
    dry_run=False,
    remove_unwanted=False,
):
    """
    Enforce the desired rulesets on a repository using the GitHub REST API.

    Args:
        github_repo: The repository object.
        expected_settings: A list of desired ruleset configurations.
        github_token: The GitHub personal access token for authentication.
        indent_level: The indentation level for logging.
        dry_run: If True, simulate the changes without applying them.
        remove_unwanted: If True, remove rulesets not in the expected settings.

    Returns:
        None
    """

    try:
        if dry_run:
            log_message(
                LogLevel.INFO,
                f"[Dry-run] Would enforce rulesets for {github_repo.full_name}",
                indent_level=indent_level,
            )
            return  # Simulate no changes

        log_message(
            LogLevel.INFO,
            f"Enforcing rulesets for {github_repo.full_name}",
            indent_level=indent_level,
        )

        # Check if there are no rulesets in the expected settings
        if not expected_settings.get("rulesets"):
            log_message(
                LogLevel.INFO,
                f"No rulesets specified in expected settings for {github_repo.full_name}",
                indent_level=indent_level,
            )
            return

        repo_api_url = github_repo.url

        # Fetch existing rulesets using the REST API
        headers = {"Authorization": f"token {github_token}"}
        response = requests.get(f"{repo_api_url}/rulesets", headers=headers)

        if response.status_code != 200:
            log_message(
                LogLevel.ERROR,
                f"Failed to fetch existing rulesets for repository '{github_repo.full_name}': {response.text}",
                indent_level=indent_level,
            )
            return

        try:
            existing_rulesets = response.json()
            if not isinstance(existing_rulesets, list):
                raise ValueError("Unexpected response format for rulesets.")
        except ValueError as e:
            log_message(
                LogLevel.ERROR,
                f"Failed to parse rulesets response for repository '{github_repo.full_name}': {e}. Response content: {response.text}",
                indent_level=indent_level,
            )
            return

        # Compare and enforce rulesets
        for ruleset_name, desired_ruleset in expected_settings["rulesets"].items():
            # Ensure desired_ruleset is a dictionary
            if not isinstance(desired_ruleset, dict):
                log_message(
                    LogLevel.WARNING,
                    f"Ruleset '{ruleset_name}' is not a valid dictionary. Skipping.",
                    indent_level=indent_level,
                )
                continue

            # Check if a matching ruleset already exists
            matching_ruleset = next(
                (
                    r
                    for r in existing_rulesets
                    if r.get("name") == desired_ruleset.get("name")
                ),
                None,
            )

            if matching_ruleset:
                # Update the existing ruleset
                log_message(
                    LogLevel.INFO,
                    f"Updating existing ruleset '{desired_ruleset['name']}' for repository '{github_repo.full_name}'",
                    indent_level=indent_level + 1,
                )
                if not dry_run:
                    update_response = requests.put(
                        f"{repo_api_url}/rulesets/{matching_ruleset['id']}",
                        headers=headers,
                        json=desired_ruleset,
                    )
                    if update_response.status_code != 200:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to update ruleset '{desired_ruleset['name']}': {update_response.text}",
                            indent_level=indent_level + 1,
                        )
            else:
                # Create a new ruleset
                log_message(
                    LogLevel.INFO,
                    f"Creating new ruleset '{desired_ruleset['name']}' for repository '{github_repo.full_name}'",
                    indent_level=indent_level + 1,
                )
                if not dry_run:
                    create_response = requests.post(
                        f"{repo_api_url}/rulesets",
                        headers=headers,
                        json=desired_ruleset,
                    )
                    if create_response.status_code != 201:
                        log_message(
                            LogLevel.ERROR,
                            f"Failed to create ruleset '{desired_ruleset['name']}': {create_response.text}",
                            indent_level=indent_level + 1,
                        )

        # Remove unwanted rulesets if enabled
        if remove_unwanted:  # Updated parameter name
            log_message(
                LogLevel.INFO,
                f"Checking for unwanted rulesets in repository '{github_repo.full_name}'.",
                indent_level=indent_level + 1,
            )
            desired_ruleset_names = {
                desired_ruleset["name"]
                for desired_ruleset in expected_settings["rulesets"].values()
            }
            for existing_ruleset in existing_rulesets:
                if existing_ruleset["name"] not in desired_ruleset_names:
                    log_message(
                        LogLevel.INFO,
                        f"Removing unwanted ruleset '{existing_ruleset['name']}' from repository '{github_repo.full_name}'.",
                        indent_level=indent_level + 1,
                    )
                    if not dry_run:
                        delete_response = requests.delete(
                            f"{repo_api_url}/rulesets/{existing_ruleset['id']}",
                            headers=headers,
                        )
                        if delete_response.status_code != 204:
                            log_message(
                                LogLevel.ERROR,
                                f"Failed to remove ruleset '{existing_ruleset['name']}': {delete_response.text}",
                                indent_level=indent_level + 1,
                            )

        log_message(
            LogLevel.INFO,
            f"Rulesets enforced for repository {github_repo.full_name}",
            indent_level=indent_level,
        )
    except Exception as e:
        log_message(
            LogLevel.ERROR,
            f"Error while enforcing rulesets in repository {github_repo.full_name}: {e}",
            indent_level=indent_level,
        )
        raise


def github_process_target_repo_stage3(
    *,
    github_target,
    github_user_login,
    repo_name,
    expected_repo_data,
    github_token,
    indent_level=0,
    dry_run=False,
    remove_unwanted_repo_settings=False,
    permissions_remove_unwanted_force_false=False,
):
    repo_owner = expected_repo_data.get("owner")
    if not repo_owner:
        return False
    # Check if the repo exists in the destination. Note that this handles exceptions and returns a status, as well as the repo object if it exists
    status, github_target_repo = github_repo_exists(
        github_target=github_target,
        repo_name=repo_name,
        repo_owner=repo_owner,
        indent_level=indent_level,
    )
    if status:
        if github_target_repo is not None:
            # Repo exists and is readable
            if github_repo_admin_permissions(
                github_repo=github_target_repo,
                github_user_login=github_user_login,
                indent_level=indent_level + 1,
            ):
                # Repo exists and is readable and we have admin permissions
                log_message(
                    LogLevel.INFO,
                    f"Current user has admin permissions on target repo {repo_owner}/{repo_name}",
                    indent_level=indent_level,
                )
        else:
            # Repo exists but is not readable
            log_message(
                LogLevel.WARNING,
                f"Repo {repo_owner}/{repo_name} exists but is not readable",
                indent_level=indent_level,
            )
            return False
    else:
        # Repo does not exist
        if expected_repo_data["create_repo"]:
            log_message(
                LogLevel.INFO,
                f"Creating target repo {repo_owner}/{repo_name}",
                indent_level=indent_level,
            )
            github_target_repo = github_create_repo(
                github_target=github_target,
                repo_name=repo_name,
                org_name=repo_owner,
                expected_settings=expected_repo_data,
                indent_level=indent_level + 1,
                dry_run=dry_run,
            )
            if not github_target_repo:
                if not dry_run:
                    log_message(
                        LogLevel.ERROR,
                        f"Failed to create target repo {repo_owner}/{repo_name}",
                        indent_level=1,
                    )
                    return False
                else:
                    github_target_repo = None
        else:
            log_message(
                LogLevel.WARNING,
                f"Repo {repo_owner}/{repo_name} does not exist, but we are not asked to create",
                indent_level=1,
            )
            # is this inconsistency an error? It is a misconfiguration, but not necessarily an error in the program
            return True

    # if we get to here, we have a target repo object

    # Check the repo owner type and plan so we can modify behaviour here as a result
    if not dry_run:
        type, plan = get_github_repo_owner_type_plan(
            github_target=github_target, repo_owner=repo_owner, repo_name=repo_name
        )
        log_message(
            LogLevel.DEBUG,
            f"Repo owner type: {type}, plan: {plan}",
            indent_level=indent_level,
        )
    else:
        log_message(
            LogLevel.INFO,
            f"[Dry-run] Would check repo owner type and plan for {repo_owner}/{repo_name}",
            indent_level=indent_level,
        )

    if expected_repo_data["enforce_repo_settings"]:
        github_enforce_repo_settings(
            github_repo=github_target_repo,
            expected_settings=expected_repo_data["repo_settings"],
            reponame=repo_name,
            repoowner=repo_owner,
            indent_level=indent_level + 1,
            remove_unwanted=remove_unwanted_repo_settings,
            dry_run=dry_run,
        )
        github_enforce_repo_user_permissions(
            github_instance=github_target,
            repo_name=repo_name,
            expected_repo_data=expected_repo_data,
            indent_level=indent_level + 1,
            dry_run=dry_run,
            permissions_remove_unwanted_force_false=permissions_remove_unwanted_force_false,
        )
        github_enforce_repo_team_permissions(
            github_instance=github_target,
            repo_name=repo_name,
            expected_repo_data=expected_repo_data,
            indent_level=indent_level + 1,
            github_token=github_token,
            dry_run=dry_run,
            permissions_remove_unwanted_force_false=permissions_remove_unwanted_force_false,
        )
        github_enforce_repo_webhooks(
            github_repo=github_target_repo,
            repo_name=repo_name,
            expected_settings=expected_repo_data,
            indent_level=indent_level + 1,
            dry_run=dry_run,
        )

    return True


def github_process_target_repo_stage6(
    *,
    github_target,
    github_user_login,
    repo_name,
    expected_repo_data,
    github_token,
    indent_level=0,
    dry_run=False,
    remove_unwanted_repo_settings=False,
    permissions_remove_unwanted_force_false=False,
    config_directory=None,
):
    repo_owner = expected_repo_data.get("owner")
    if not repo_owner:
        return False
    status, github_target_repo = github_repo_exists(
        github_target=github_target,
        repo_name=repo_name,
        repo_owner=repo_owner,
        indent_level=indent_level,
    )
    if status:
        if github_target_repo is not None:
            # Repo exists and is readable
            if github_repo_admin_permissions(
                github_repo=github_target_repo,
                github_user_login=github_user_login,
                indent_level=indent_level + 1,
            ):
                # Repo exists and is readable and we have admin permissions
                log_message(
                    LogLevel.INFO,
                    f"Current user has admin permissions on target repo {repo_owner}/{repo_name}",
                    indent_level=indent_level,
                )
        else:
            # Repo exists but is not readable
            log_message(
                LogLevel.WARNING,
                f"Repo {repo_owner}/{repo_name} exists but is not readable",
                indent_level=indent_level,
            )
            return False
    else:
        # Repo does not exist
        log_message(
            LogLevel.WARNING,
            f"Repo {repo_owner}/{repo_name} does not exist",
            indent_level=1,
        )
        return False

    github_enforce_gitignore(
        github_repo=github_target_repo,
        repo_name=repo_name,
        repo_owner=repo_owner,
        expected_settings=expected_repo_data,
        indent_level=indent_level + 1,
        dry_run=dry_run,
        config_directory=config_directory,
    )
    github_enforce_branch_protection(
        github_repo=github_target_repo,
        repo_name=repo_name,
        repo_owner=repo_owner,
        expected_settings=expected_repo_data,
        indent_level=indent_level + 1,
        dry_run=dry_run,
        remove_unwanted=remove_unwanted_repo_settings,
        github_token=github_token,
    )
    github_enforce_rulesets(
        github_repo=github_target_repo,
        expected_settings=expected_repo_data,
        github_token=github_token,
        indent_level=indent_level + 1,
        dry_run=dry_run,
        remove_unwanted=remove_unwanted_repo_settings,
    )
    github_enforce_codeowners(
        github_repo=github_target_repo,
        repo_name=repo_name,
        repo_owner=repo_owner,
        expected_settings=expected_repo_data,
        indent_level=indent_level + 1,
        dry_run=dry_run,
    )
    return True


def github_repo_admin_permissions(
    *, github_repo, github_user_login=None, indent_level=0
):
    try:
        if not github_user_login:
            raise ValueError("Internal error: No GitHub user login provided")
        permissions = github_repo.get_collaborator_permission(github_user_login)
        if permissions == "admin":
            log_message(
                LogLevel.DEBUG,
                f"Current user has admin permissions on repo",
                indent_level=indent_level,
            )
            return True
        else:
            log_message(
                LogLevel.DEBUG,
                f"Current user missing admin permissions on repo",
                indent_level=indent_level,
            )
            return False
    except GithubException as e:
        raise ("An error occurred checking admin permissions on repo: {}", e)


def github_repo_exists(*, github_target, repo_name, repo_owner, indent_level=0):
    try:
        grepo = github_target.get_repo(f"{repo_owner}/{repo_name}")
        log_message(
            LogLevel.DEBUG,
            "Repo exists in target and is readable",
            indent_level=indent_level,
        )
        return True, grepo
    except GithubException as e:
        if e.status == 403:
            log_message(
                LogLevel.DEBUG,
                "Repo exists in target but is not readable",
                indent_level=indent_level,
            )
            return True, None
        elif e.status == 404:
            log_message(
                LogLevel.DEBUG,
                "Repo does not exist in target",
                indent_level=indent_level,
            )
            return False, None
        else:
            raise Exception(
                f"An error occurred checking if repo {repo_owner}/{repo_name} exists: {e}"
            )


def transform_github_webhook_to_config(webhook):
    """
    Transform a webhook object into the JSON format expected by create_or_update_webhook.

    Args:
        webhook: A webhook object returned by the GitHub API.

    Returns:
        A dictionary representing the webhook configuration.
    """
    try:
        config = {
            "url": webhook.config.get("url"),
            "events": webhook.events,
            "secret": webhook.config.get("secret"),
            "content_type": webhook.config.get("content_type", "json"),
            "insecure_ssl": webhook.config.get("insecure_ssl", "0"),
            "active": webhook.active,
        }
        return config
    except AttributeError as e:
        raise ValueError(f"Invalid webhook object: {e}")


def update_file_in_repo(
    *, repo, file_path, local_file_path, commit_message, branch, dry_run=False
):
    try:
        # Read the local file content
        with open(local_file_path, "r") as file:
            local_content = file.read()

        # Check if the file exists in the repository
        try:
            contents = repo.get_contents(file_path, ref=branch)
            repo_content = contents.decoded_content.decode("utf-8")
            # If the file exists and is different, update it
            if local_content != repo_content:
                if dry_run:
                    log_message(
                        LogLevel.INFO,
                        f"[Dry-run] Would update file '{file_path}' in repository '{repo.full_name}'",
                    )
                    return
                else:
                    repo.update_file(
                        contents.path,
                        commit_message,
                        local_content,
                        contents.sha,
                        branch=branch,
                    )
                    log_message(
                        LogLevel.INFO,
                        "Updated file '{}' in repository '{}'",
                        file_path,
                        repo.full_name,
                    )
            else:
                log_message(
                    LogLevel.INFO,
                    "File '{}' is already up to date in repository '{}'",
                    file_path,
                    repo.full_name,
                )
        except GithubException as e:
            if e.status == 404:
                # File does not exist, create it
                if dry_run:
                    log_message(
                        LogLevel.INFO,
                        f"[Dry-run] Would create file '{file_path}' in repository '{repo.full_name}'",
                    )
                    return
                else:
                    repo.create_file(
                        file_path, commit_message, local_content, branch=branch
                    )
                    log_message(
                        LogLevel.INFO,
                        "Created file '{}' in repository '{}'",
                        file_path,
                        repo.full_name,
                    )
            else:
                # Handle other exceptions
                raise
    except Exception as e:
        log_message(
            LogLevel.ERROR,
            "Failed to update file in repository '{}': {}",
            repo.full_name,
            e,
        )
