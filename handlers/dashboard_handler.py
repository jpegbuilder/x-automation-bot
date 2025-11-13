import json
import logging
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler - ULTRA VERBOSE VERSION"""

    def log_message(self, fmt, *args):
        # Log HTTP requests
        logger.info(f"HTTP REQUEST: {fmt % args}")

    def _set_headers(self, code=200, ctype='application/json'):
        logger.debug(f"Setting headers: code={code}, content-type={ctype}")
        self.send_response(code)
        self.send_header('Content-type', ctype)
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

    def start_all_profiles_backend(self, vps_filter='all', phase_filter='all', batch_filter='all'):
        """Start all profiles that meet the filter criteria"""
        logger.info(f"=== START_ALL_PROFILES_BACKEND CALLED ===")
        logger.info(f"Filters: vps={vps_filter}, phase={phase_filter}, batch={batch_filter}")

        def _start_all_async():
            try:
                logger.info("_start_all_async: Starting execution")
                alive_profiles = []

                logger.info("_start_all_async: Acquiring profiles_lock")
                with self.server.profiles_lock:
                    logger.info(f"_start_all_async: Processing {len(self.server.profiles)} profiles")
                    for pid, info in self.server.profiles.items():
                        if vps_filter != 'all' and info.get('vps_status', 'None') != vps_filter:
                            continue
                        if phase_filter != 'all' and info.get('phase', 'None') != phase_filter:
                            continue
                        if batch_filter != 'all' and info.get('batch', 'None') != batch_filter:
                            continue

                        airtable_status = info.get('airtable_status', 'Alive')
                        if airtable_status == 'Alive':
                            thread = info.get('thread')
                            if thread is None or not thread.is_alive():
                                alive_profiles.append(pid)

                if not alive_profiles:
                    logger.warning("_start_all_async: No profiles to start")
                    return

                alive_profiles.sort(key=lambda x: int(x))
                logger.info(f"_start_all_async: Starting {len(alive_profiles)} profiles")
                logger.info(f"_start_all_async: Profile IDs: {alive_profiles[:10]}...")

                config = self.server.config_manager.load_config() or {}
                delay_config = config.get('delays', {})
                profile_delay = delay_config.get('profile_start_delay', 3)

                batch_size = 2
                for i in range(0, len(alive_profiles), batch_size):
                    batch = alive_profiles[i:i + batch_size]
                    logger.info(f"_start_all_async: Starting batch {i // batch_size + 1}: {batch}")

                    for pid in batch:
                        try:
                            logger.info(f"_start_all_async: Calling start_profile for {pid}")
                            result = self.server.profile_controller.start_profile(pid)
                            logger.info(f"_start_all_async: start_profile({pid}) returned: {result}")
                            time.sleep(5)
                        except Exception as e:
                            logger.error(f"_start_all_async: Error starting profile {pid}: {e}")
                            logger.error(traceback.format_exc())

                    if i + batch_size < len(alive_profiles):
                        time.sleep(0)

                logger.info("_start_all_async: Completed")

            except Exception as e:
                logger.error(f"_start_all_async: CRITICAL ERROR: {e}")
                logger.error(traceback.format_exc())

        try:
            logger.info("start_all_profiles_backend: Submitting async task to executor")
            self.server.profile_executor.submit(_start_all_async)
            logger.info("start_all_profiles_backend: Task submitted successfully")
            return True, -1
        except Exception as e:
            logger.error(f"start_all_profiles_backend: Failed to submit task: {e}")
            logger.error(traceback.format_exc())
            return False, 0

    def do_GET(self):
        logger.info("=" * 80)
        logger.info(f">>> INCOMING GET REQUEST: {self.path}")
        logger.info("=" * 80)

        try:
            with self.server.request_lock:
                self.server.request_counter += 1
                req_id = self.server.request_counter
                logger.info(f"Request ID: {req_id}")

            u = urlparse(self.path)
            logger.info(f"Parsed URL - path: {u.path}, query: {u.query}")

            if u.path == '/':
                logger.info("Serving dashboard.html")
                self._set_headers(200, 'text/html')
                with open('html/dashboard.html', 'rb') as f:
                    self.wfile.write(f.read())
                logger.info("dashboard.html served successfully")
                return

            if u.path == '/api/status':
                logger.info("Handling /api/status request")
                try:
                    qs = parse_qs(u.query)
                    page = int(qs.get('page', [1])[0])
                    per_page = int(qs.get('per_page', [100])[0])
                    filter_status = qs.get('filter', ['all'])[0]
                    vps_filter = qs.get('vps', ['all'])[0]
                    phase_filter = qs.get('phase', ['all'])[0]
                    batch_filter = qs.get('batch', ['all'])[0]

                    logger.info(
                        f"/api/status params: page={page}, per_page={per_page}, filter={filter_status}, vps={vps_filter}, phase={phase_filter}, batch={batch_filter}")

                    # Get cache from server
                    logger.info("Getting cached data from dashboard_cache_manager")
                    cached_data = self.server.dashboard_cache_manager.get_cached_data()

                    if not cached_data.get('profiles'):
                        logger.warning("Dashboard cache is empty, forcing rebuild...")
                        self.server.dashboard_cache_manager.update_cache()
                        cached_data = self.server.dashboard_cache_manager.get_cached_data()

                    logger.info(f"Processing {len(cached_data.get('profiles', {}))} profiles from cache")

                    filtered_profiles = {}
                    for pid, info in cached_data['profiles'].items():
                        persistent_status = cached_data['status'].get(pid)
                        vps_status = info.get('vps_status', 'None')
                        phase = info.get('phase', 'None')
                        batch = info.get('batch', 'None')

                        if vps_filter != 'all' and vps_status != vps_filter:
                            continue
                        if phase_filter != 'all' and phase != phase_filter:
                            continue
                        if batch_filter != 'all' and batch != batch_filter:
                            continue

                        airtable_status = info.get('airtable_status', 'Alive')
                        if isinstance(airtable_status, list):
                            airtable_status = airtable_status[0] if airtable_status else 'Alive'

                        if airtable_status == 'Alive':
                            display_status = info['status']
                        elif airtable_status == 'Follow Block':
                            display_status = 'Blocked'
                        elif airtable_status == 'Suspended':
                            display_status = 'Suspended'
                        else:
                            if persistent_status == 'blocked':
                                display_status = 'Blocked'
                            elif persistent_status == 'suspended':
                                display_status = 'Suspended'
                            else:
                                display_status = info['status']

                        if filter_status == 'all':
                            include = True
                        elif filter_status == 'alive':
                            include = display_status not in ['Blocked', 'Suspended']
                        elif filter_status == 'blocked':
                            include = display_status == 'Blocked'
                        elif filter_status == 'suspended':
                            include = display_status == 'Suspended'
                        else:
                            include = True

                        if include:
                            stats = cached_data['stats'].get(pid, {
                                'last_run': 0,
                                'today': 0,
                                'total_all_time': 0
                            })

                            display_airtable_status = info.get('airtable_status', 'Alive')
                            if isinstance(display_airtable_status, list):
                                display_airtable_status = display_airtable_status[
                                    0] if display_airtable_status else 'Alive'

                            filtered_profiles[pid] = {
                                'status': display_status,
                                'stats': stats,
                                'username': info.get('username', 'Unknown'),
                                'adspower_name': info.get('adspower_name'),
                                'airtable_status': display_airtable_status,
                                'persistent_status': persistent_status,
                                'vps_status': vps_status,
                                'phase': phase,
                                'batch': batch,
                                'profile_number': info.get('profile_number', pid),
                                'has_assigned_followers': info.get('has_assigned_followers', False),
                                'assigned_followers_count': info.get('assigned_followers_count', 0)
                            }

                    def get_sort_key(pid):
                        try:
                            profile_num = filtered_profiles[pid].get('profile_number', '999999')
                            return int(profile_num)
                        except (ValueError, TypeError):
                            return 999999

                    sorted_ids = sorted(filtered_profiles.keys(), key=get_sort_key)
                    total = len(sorted_ids)
                    page_profiles = filtered_profiles

                    active_count = self.server.concurrency_manager.get_active_profiles_count()
                    pending_count = len(self.server.pending_profiles_queue)

                    logger.info(f"Returning {total} profiles, {active_count} active, {pending_count} pending")

                    response = {
                        'profiles': page_profiles,
                        'pagination': {
                            'current_page': 1,
                            'total_pages': 1,
                            'total_profiles': total,
                            'per_page': total,
                            'start_index': 1 if total > 0 else 0,
                            'end_index': total
                        },
                        'remaining_usernames': self.server.username_manager.get_remaining_count(),
                        'concurrent_info': {
                            'active_profiles': active_count,
                            'max_concurrent': self.server.MAX_CONCURRENT_PROFILES,
                            'pending_profiles': pending_count
                        },
                        'filter': filter_status,
                        'vps_filter': vps_filter,
                        'phase_filter': phase_filter,
                        'batch_filter': batch_filter,
                        'vps_options': self.server.airtable_manager.get_vps_options(),
                        'phase_options': self.server.airtable_manager.get_phase_options(),
                        'batch_options': self.server.airtable_manager.get_batch_options()
                    }

                    self._set_headers()
                    self.wfile.write(json.dumps(response).encode())
                    logger.info("/api/status completed successfully")
                    return
                except Exception as e:
                    logger.error(f"ERROR in /api/status: {e}")
                    logger.error(traceback.format_exc())
                    self._set_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode())
                    return

            if u.path == '/api/control':
                logger.info("*** HANDLING /api/control REQUEST ***")
                try:
                    qs = parse_qs(u.query)
                    act = qs.get('action', [''])[0]
                    pid = qs.get('profile', [''])[0]

                    logger.info(f"Control action: '{act}', profile: '{pid}'")

                    if act == 'start':
                        logger.info(f">>> ACTION: START PROFILE {pid} <<<")
                        try:
                            logger.info(
                                f"Checking if profile_controller exists: {hasattr(self.server, 'profile_controller')}")
                            if not hasattr(self.server, 'profile_controller'):
                                logger.error("CRITICAL: profile_controller not found on server!")
                                self._set_headers(500)
                                self.wfile.write(json.dumps(
                                    {'success': False, 'error': 'profile_controller not initialized'}).encode())
                                return

                            logger.info(f"Calling profile_controller.start_profile({pid})")
                            ok = self.server.profile_controller.start_profile(pid)
                            logger.info(f"start_profile({pid}) returned: {ok}")

                            self._set_headers()
                            self.wfile.write(json.dumps({'success': ok}).encode())
                            logger.info(f"Response sent: success={ok}")
                            return
                        except Exception as e:
                            logger.error(f"EXCEPTION starting profile {pid}: {e}")
                            logger.error(traceback.format_exc())
                            self._set_headers(500)
                            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
                            return

                    elif act == 'stop':
                        logger.info(f">>> ACTION: STOP PROFILE {pid} <<<")
                        try:
                            logger.info(f"Calling profile_controller.stop_profile({pid})")
                            ok = self.server.profile_controller.stop_profile(pid)
                            logger.info(f"stop_profile({pid}) returned: {ok}")

                            self._set_headers()
                            self.wfile.write(json.dumps({'success': ok}).encode())
                            logger.info(f"Response sent: success={ok}")
                            return
                        except Exception as e:
                            logger.error(f"EXCEPTION stopping profile {pid}: {e}")
                            logger.error(traceback.format_exc())
                            self._set_headers(500)
                            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
                            return

                    elif act == 'test':
                        logger.info(f">>> ACTION: TEST PROFILE {pid} <<<")
                        try:
                            logger.info(f"Calling profile_controller.test_profile({pid})")
                            ok = self.server.profile_controller.test_profile(pid)
                            logger.info(f"test_profile({pid}) returned: {ok}")

                            self._set_headers()
                            self.wfile.write(json.dumps({'success': ok}).encode())
                            logger.info(f"Response sent: success={ok}")
                            return
                        except Exception as e:
                            logger.error(f"EXCEPTION testing profile {pid}: {e}")
                            logger.error(traceback.format_exc())
                            self._set_headers(500)
                            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
                            return

                    elif act == 'start_all':
                        logger.info(">>> ACTION: START ALL PROFILES <<<")
                        try:
                            vps = qs.get('vps', ['all'])[0]
                            phase = qs.get('phase', ['all'])[0]
                            batch = qs.get('batch', ['all'])[0]

                            logger.info(f"start_all filters: vps={vps}, phase={phase}, batch={batch}")
                            logger.info("Calling start_all_profiles_backend...")

                            success, count = self.start_all_profiles_backend(vps, phase, batch)

                            logger.info(f"start_all_profiles_backend returned: success={success}, count={count}")

                            self._set_headers()
                            self.wfile.write(json.dumps({'success': success, 'count': count}).encode())
                            logger.info(f"Response sent: success={success}, count={count}")
                            return
                        except Exception as e:
                            logger.error(f"EXCEPTION in start_all: {e}")
                            logger.error(traceback.format_exc())
                            self._set_headers(500)
                            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
                            return
                    else:
                        logger.warning(f"Unknown action: '{act}'")
                        self._set_headers()
                        self.wfile.write(json.dumps({'success': False, 'error': f'Unknown action: {act}'}).encode())
                        return
                except Exception as e:
                    logger.error(f"EXCEPTION in /api/control: {e}")
                    logger.error(traceback.format_exc())
                    self._set_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
                    return

            logger.warning(f"404 - Unknown path: {u.path}")
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': f'Not found: {u.path}'}).encode())

        except Exception as e:
            logger.error(f"CRITICAL ERROR in do_GET: {e}")
            logger.error(traceback.format_exc())
            try:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': f'Internal server error: {str(e)}'}).encode())
            except Exception as e2:
                logger.error(f"Failed to send error response: {e2}")