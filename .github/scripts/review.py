import os
import sys
# import anthropic
import requests
from git import Repo
from typing import List, Dict, Tuple
import re
from anthropic import Anthropic

class CodeReviewer:
    def __init__(self):
        # self.anthropic = anthropic.Client(os.getenv('ANTHROPIC_API_KEY'))
        self.anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.pr_number = os.getenv('PR_NUMBER')
        self.repo_name = os.getenv('REPO_NAME')
        self.base_url = f"https://api.github.com/repos/{self.repo_name}"
        
        if not all([self.anthropic, self.github_token, self.pr_number, self.repo_name]):
            raise EnvironmentError("Missing required environment variables")

    def get_pr_diff(self) -> List[Dict]:
        """
        Fetches the file changes from the pull request
        Returns a list of changed files with their diffs
        """
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3.diff"
        }
        response = requests.get(
            f"{self.base_url}/pulls/{self.pr_number}",
            headers=headers
        )
        response.raise_for_status()
        
        # Parse the diff to get file changes
        diff_files = []
        current_file = None
        current_diff = []
        
        for line in response.text.split('\n'):
            if line.startswith('diff --git'):
                if current_file:
                    diff_files.append({
                        'file': current_file,
                        'diff': '\n'.join(current_diff)
                    })
                current_file = re.search(r'b/(.+)$', line).group(1)
                current_diff = [line]
            else:
                if current_file:
                    current_diff.append(line)
        
        if current_file:
            diff_files.append({
                'file': current_file,
                'diff': '\n'.join(current_diff)
            })
            
        return diff_files

    def review_code(self, diff_files: List[Dict]) -> List[Dict]:
        """
        Sends code to Claude for review and parses the response
        Returns a list of review comments
        """
        review_comments = []
        
        for file_diff in diff_files:
            prompt = f"""
            Please review this code diff and provide specific, actionable feedback.
            Focus on:
            - Potential bugs or errors
            - Security concerns
            - Performance improvements
            - Code style and best practices
            
            For each issue, specify:
            1. The line number
            2. The specific issue
            3. A suggested fix
            
            The diff is from file: {file_diff['file']}
            
            {file_diff['diff']}
            """
            
            response = self.anthropic.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0,
                system="You are an expert code reviewer. Provide specific, actionable feedback focused on improving code quality and preventing issues.",
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse Claude's response to extract review comments
            comments = self._parse_review_comments(response.content[0].text, file_diff['file'])
            review_comments.extend(comments)
        
        return review_comments

    def _parse_review_comments(self, review_text: str, filename: str) -> List[Dict]:
        """
        Parses Claude's review response into structured comments
        Returns a list of comment dictionaries with file, line, and content
        """
        comments = []
        current_comment = None
        
        for line in review_text.split('\n'):
            # Look for line number indicators
            line_match = re.search(r'(?:Line|line) (\d+):', line)
            if line_match:
                if current_comment:
                    comments.append(current_comment)
                    
                current_comment = {
                    'file': filename,
                    'line': int(line_match.group(1)),
                    'content': line.split(':', 1)[1].strip()
                }
            elif current_comment and line.strip():
                current_comment['content'] += '\n' + line.strip()
        
        if current_comment:
            comments.append(current_comment)
            
        return comments

    def post_review_comments(self, comments: List[Dict]):
        """
        Posts review comments to GitHub pull request
        """
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        for comment in comments:
            data = {
                "body": comment['content'],
                "commit_id": os.getenv('GITHUB_SHA'),
                "path": comment['file'],
                "line": comment['line'],
                "side": "RIGHT"
            }
            
            response = requests.post(
                f"{self.base_url}/pulls/{self.pr_number}/comments",
                headers=headers,
                json=data
            )
            response.raise_for_status()

def main():
    try:
        reviewer = CodeReviewer()
        diff_files = reviewer.get_pr_diff()
        review_comments = reviewer.review_code(diff_files)
        reviewer.post_review_comments(review_comments)
        print(f"Successfully posted {len(review_comments)} review comments")
    except Exception as e:
        print(f"Error during code review: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()