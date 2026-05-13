from curl_cffi import requests
from typing import Optional, Dict, Any, Generator, Literal, List
import json
from .pow import DeepSeekPOW
import importlib.metadata
import sys
from pathlib import Path
import subprocess
import time

ThinkingMode = Literal['detailed', 'simple', 'disabled']
SearchMode = Literal['enabled', 'disabled']

MODEL_FLASH = "default"   # DeepSeek-V4-Flash (standard / instant)
MODEL_PRO   = "expert"    # DeepSeek-V4-Pro (expert mode)
MODEL_DEFAULT = MODEL_FLASH

class DeepSeekError(Exception):
    pass

class AuthenticationError(DeepSeekError):
    pass

class RateLimitError(DeepSeekError):
    pass

class NetworkError(DeepSeekError):
    pass

class CloudflareError(DeepSeekError):
    pass

class APIError(DeepSeekError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

class DeepSeekAPI:
    BASE_URL = "https://chat.deepseek.com/api/v0"

    def __init__(self, auth_token: str):
        if not auth_token or not isinstance(auth_token, str):
            raise AuthenticationError("Invalid auth token provided")

        try:
            importlib.metadata.version('curl-cffi')
        except importlib.metadata.PackageNotFoundError:
            print("\033[93mWarning: curl-cffi not found. Please install it using: pip install curl-cffi\033[0m", file=sys.stderr)

        self.auth_token = auth_token
        self.pow_solver = DeepSeekPOW()
        self._current_path = None
        self._in_thinking = False

        cookies_path = Path(__file__).parent / 'cookies.json'
        try:
            with open(cookies_path, 'r') as f:
                cookie_data = json.load(f)
                self.cookies = cookie_data.get('cookies', {})
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.cookies = {}

    def _get_headers(self, pow_response: Optional[str] = None, chat_session_id: Optional[str] = None) -> Dict[str, str]:
        headers = {
            'accept': '*/*',
            'accept-language': 'en,fr-FR;q=0.9,fr;q=0.8,es-ES;q=0.7,es;q=0.6,en-US;q=0.5,am;q=0.4,de;q=0.3',
            'authorization': f'Bearer {self.auth_token}',
            'content-type': 'application/json',
            'origin': 'https://chat.deepseek.com',
            'referer': 'https://chat.deepseek.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0',
            'x-app-version': '2.0.0',
            'x-client-locale': 'en_US',
            'x-client-platform': 'web',
            'x-client-version': '2.0.0',
        }

        if chat_session_id:
            headers['referer'] = f'https://chat.deepseek.com/a/chat/s/{chat_session_id}'

        if pow_response:
            headers['x-ds-pow-response'] = pow_response

        return headers

    def _refresh_cookies(self) -> None:
        try:
            script_path = Path(__file__).parent / 'bypass.py'
            subprocess.run([sys.executable, script_path], check=True)
            time.sleep(2)
            cookies_path = Path(__file__).parent / 'cookies.json'
            with open(cookies_path, 'r') as f:
                cookie_data = json.load(f)
                self.cookies = cookie_data.get('cookies', {})
        except Exception as e:
            print(f"\033[93mWarning: Failed to refresh cookies: {e}\033[0m", file=sys.stderr)

    def _make_request(self, method: str, endpoint: str, json_data: Dict[str, Any], pow_required: bool = False) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        retry_count = 0
        max_retries = 2

        while retry_count < max_retries:
            try:
                headers = self._get_headers()
                if pow_required:
                    challenge = self._get_pow_challenge()
                    pow_response = self.pow_solver.solve_challenge(challenge)
                    headers = self._get_headers(pow_response)

                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    cookies=self.cookies,
                    impersonate='chrome',
                    timeout=None
                )

                if "<!DOCTYPE html>" in response.text and "Just a moment" in response.text:
                    if retry_count < max_retries - 1:
                        self._refresh_cookies()
                        retry_count += 1
                        continue

                if response.status_code == 401:
                    raise AuthenticationError("Invalid or expired authentication token")
                elif response.status_code == 429:
                    raise RateLimitError("API rate limit exceeded")
                elif response.status_code >= 500:
                    raise APIError(f"Server error occurred: {response.text}", response.status_code)
                elif response.status_code != 200:
                    raise APIError(f"API request failed: {response.text}", response.status_code)

                return response.json()

            except requests.exceptions.RequestException as e:
                raise NetworkError(f"Network error occurred: {str(e)}")
            except json.JSONDecodeError:
                raise APIError("Invalid JSON response from server")

        raise APIError("Failed to bypass Cloudflare protection after multiple attempts")

    def _get_pow_challenge(self) -> Dict[str, Any]:
        try:
            response = self._make_request(
                'POST',
                '/chat/create_pow_challenge',
                {'target_path': '/api/v0/chat/completion'}
            )
            return response['data']['biz_data']['challenge']
        except KeyError:
            raise APIError("Invalid challenge response format from server")

    def create_chat_session(self) -> str:
        """Creates a new chat session and returns the session ID"""
        try:
            response = self._make_request(
                'POST',
                '/chat_session/create',
                {'character_id': None}
            )
            biz_data = response['data']['biz_data']
            if 'chat_session' in biz_data:
                return biz_data['chat_session']['id']
            return biz_data['id']
        except KeyError:
            raise APIError("Invalid session creation response format from server")

    def delete_chat_session(self, chat_session_id: str) -> bool:
        """Delete a chat session. Returns True if successful."""
        try:
            response = self._make_request(
                'POST',
                '/chat_session/delete',
                {'chat_session_id': chat_session_id}
            )
            return response.get('code') == 0
        except Exception as e:
            raise NetworkError(f"Failed to delete session: {str(e)}")

    def stop_stream(self, chat_session_id: str, message_id: str) -> bool:
        """Stops an ongoing stream on the server"""
        try:
            self._make_request(
                'POST',
                '/chat/stop_stream',
                {
                    'chat_session_id': chat_session_id,
                    'message_id': int(message_id) if str(message_id).isdigit() else message_id
                }
            )
            return True
        except Exception as e:
            return False

    def get_current_user(self) -> Dict[str, Any]:
        """Fetches the current user information"""
        try:
            response = self._make_request(
                'GET',
                '/users/current',
                json_data=None
            )
            return response['data']['biz_data']
        except KeyError:
            raise APIError("Invalid user info response format from server")

    def get_chat_sessions(self) -> List[Dict[str, Any]]:
        """Lists the user's chat sessions"""
        try:
            response = self._make_request(
                'GET',
                '/chat_session/fetch_page?lte_cursor.pinned=false',
                json_data=None
            )
            return response['data']['biz_data']['chat_sessions']
        except KeyError:
            raise APIError("Invalid chat sessions response format from server")

    def chat_completion(self,
                    chat_session_id: str,
                    prompt: str,
                    parent_message_id: Optional[str] = None,
                    thinking_enabled: bool = True,
                    search_enabled: bool = False,
                    model_type: str = MODEL_DEFAULT) -> Generator[Dict[str, Any], None, None]:
        """Send a message and get streaming response using the new stateful format"""
        if not prompt or not isinstance(prompt, str):
            raise ValueError("Prompt must be a non-empty string")
        if not chat_session_id or not isinstance(chat_session_id, str):
            raise ValueError("Chat session ID must be a non-empty string")

        json_data = {
            'chat_session_id': chat_session_id,
            'parent_message_id': parent_message_id,
            'model_type': model_type,
            'prompt': prompt,
            'ref_file_ids': [],
            'thinking_enabled': thinking_enabled,
            'search_enabled': search_enabled,
        }

        self._current_path = None
        self._in_thinking = True 
        self._fragment_streaming = False  

        try:
            headers = self._get_headers(
                pow_response=self.pow_solver.solve_challenge(
                    self._get_pow_challenge()
                )
            )

            response = requests.post(
                f"{self.BASE_URL}/chat/completion",
                headers=headers,
                json=json_data,
                cookies=self.cookies,
                impersonate='chrome',
                stream=True,
                timeout=None
            )

            if response.status_code != 200:
                error_text = next(response.iter_lines(), b'').decode('utf-8', 'ignore')
                if response.status_code == 401:
                    raise AuthenticationError("Invalid or expired authentication token")
                elif response.status_code == 429:
                    raise RateLimitError("API rate limit exceeded")
                else:
                    raise APIError(f"API request failed: {error_text}", response.status_code)

            self._current_event = None

            for chunk in response.iter_lines():
                if not chunk: continue
                try:
                    line = chunk.decode('utf-8', 'ignore')

                    if line.startswith('event: '):
                        self._current_event = line[7:].strip()
                        if self._current_event == 'ready':
                            self._current_path = None
                            self._in_thinking = False
                        continue

                    if line.startswith('data: '):
                        data_json = json.loads(line[6:])
                        parsed = self._parse_deepseek_data(data_json)
                        if parsed:
                            yield parsed
                except Exception as e:
                    print(f"\n[DEBUG] Parsing error: {e}. Line: {line}")
                    continue

        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Network error occurred during streaming: {str(e)}")

    def _parse_deepseek_data(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse the structured data from DeepSeek's SSE stream."""
        if self._current_event == 'ready':
            if 'response_message_id' in data:
                return {'type': 'status', 'message_id': data['response_message_id']}
            return None

        p = data.get('p', '')
        v = data.get('v')
        o = data.get('o', '')

        if not p and isinstance(v, dict):
            resp = v.get('response', {})
            if isinstance(resp, dict):
                frags = resp.get('fragments', [])
                if isinstance(frags, list) and frags:
                    last_frag = frags[-1]
                    ftype = str(last_frag.get('type', '')).upper()
                    if ftype:
                        self._in_thinking = (ftype == 'THINK')
                        self._fragment_streaming = True
                    
                    content = last_frag.get('content', '')
                    if content:
                        return {
                            'type': 'thinking' if self._in_thinking else 'text',
                            'content': content
                        }
                
                if 'message_id' in resp:
                    return {'type': 'status', 'message_id': resp['message_id']}
            return None

        if p == 'response/fragments' and o == 'APPEND' and isinstance(v, list):
            if v:
                frag = v[0]
                ftype = str(frag.get('type', '')).upper()
                if ftype:
                    self._in_thinking = (ftype == 'THINK')
                    self._fragment_streaming = True
                content = frag.get('content', '')
                if content:
                    return {
                        'type': 'thinking' if self._in_thinking else 'text',
                        'content': content
                    }
            return None

        if p == 'response/fragments/-1/content' and isinstance(v, str):
            self._fragment_streaming = True
            return {
                'type': 'thinking' if self._in_thinking else 'text',
                'content': v
            }

        if not p and isinstance(v, str) and self._fragment_streaming:
            return {
                'type': 'thinking' if self._in_thinking else 'text',
                'content': v
            }

        if (p == 'response/status' and v == 'FINISHED') or \
           (o == 'BATCH' and any(x.get('p') == 'quasi_status' and x.get('v') == 'FINISHED' for x in (v if isinstance(v, list) else []))):
            self._fragment_streaming = False
            return None

        return None


