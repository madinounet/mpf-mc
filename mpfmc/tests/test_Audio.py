import logging

from mpfmc.tests.MpfMcTestCase import MpfMcTestCase
from unittest.mock import MagicMock, call

try:
    from mpfmc.core.audio import SoundSystem
    from mpfmc.assets.sound import SoundStealingMethod
except ImportError:
    SoundSystem = None
    SoundStealingMethod = None
    logging.warning("mpfmc.core.audio library could not be loaded. Audio "
                    "features will not be available")


class TestAudio(MpfMcTestCase):
    """
    Tests all the audio features in the media controller.  The core audio library is a
    custom extension library written in Cython that interfaces with the SDL2 and
    SDL_Mixer libraries.
    """
    def get_machine_path(self):
        return 'tests/machine_files/audio'

    def get_config_file(self):
        return 'test_audio.yaml'

    def test_typical_sound_system(self):
        """ Tests the sound system and audio interface with typical settings """

        if SoundSystem is None:
            log = logging.getLogger('TestAudio')
            log.warning("Sound system is not enabled - skipping audio tests")
            self.skipTest("Sound system is not enabled")

        self.assertIsNotNone(self.mc.sound_system)
        interface = self.mc.sound_system.audio_interface
        self.assertIsNotNone(interface)

        # Check basic audio interface settings
        settings = interface.get_settings()
        self.assertIsNotNone(settings)
        self.assertEqual(settings['buffer_samples'], 2048)
        self.assertEqual(settings['audio_channels'], 2)
        self.assertEqual(settings['sample_rate'], 44100)

        # Check static conversion functions (gain, samples)
        self.assertEqual(interface.string_to_gain('0db'), 1.0)
        self.assertAlmostEqual(interface.string_to_gain('-3 db'), 0.707945784)
        self.assertAlmostEqual(interface.string_to_gain('-6 db'), 0.501187233)
        self.assertAlmostEqual(interface.string_to_gain('-17.5 db'), 0.133352143)
        self.assertEqual(interface.string_to_gain('3db'), 1.0)
        self.assertEqual(interface.string_to_gain('0.25'), 0.25)
        self.assertEqual(interface.string_to_gain('-3'), 0.0)

        self.assertEqual(interface.string_to_samples("234"), 234)
        self.assertEqual(interface.string_to_samples("234.73"), 234)
        self.assertEqual(interface.string_to_samples("-23"), -23)
        self.assertEqual(interface.string_to_samples("2s"), 88200)
        self.assertEqual(interface.string_to_samples("2 ms"), 88)
        self.assertEqual(interface.string_to_samples("23.5 ms"), 1036)
        self.assertEqual(interface.string_to_samples("-2 ms"), -88)

        self.assertEqual(interface.convert_seconds_to_buffer_length(2.25), 396900)
        self.assertEqual(interface.convert_buffer_length_to_seconds(396900), 2.25)

        # Check tracks
        self.assertEqual(interface.get_track_count(), 3)
        track_voice = interface.get_track_by_name("voice")
        self.assertIsNotNone(track_voice)
        self.assertEqual(track_voice.name, "voice")
        self.assertAlmostEqual(track_voice.volume, 0.6, 1)
        self.assertEqual(track_voice.max_simultaneous_sounds, 1)

        track_sfx = interface.get_track_by_name("sfx")
        self.assertIsNotNone(track_sfx)
        self.assertEqual(track_sfx.name, "sfx")
        self.assertAlmostEqual(track_sfx.volume, 0.4, 1)
        self.assertEqual(track_sfx.max_simultaneous_sounds, 8)

        track_music = interface.get_track_by_name("music")
        self.assertIsNotNone(track_music)
        self.assertEqual(track_music.name, "music")
        self.assertAlmostEqual(track_music.volume, 0.5, 1)
        self.assertEqual(track_music.max_simultaneous_sounds, 1)

        self.assertTrue(self.mc, 'sounds')

        # Mock BCP send method
        self.mc.bcp_processor.send = MagicMock()

        # Allow some time for sound assets to load
        self.advance_time(2)

        # Start mode
        self.send(bcp_command='mode_start', name='mode1', priority=500)
        self.assertTrue(self.mc.modes['mode1'].active)
        self.assertEqual(self.mc.modes['mode1'].priority, 500)

        # /sounds/sfx
        self.assertIn('198361_sfx-028', self.mc.sounds)     # .wav
        self.assertIn('210871_synthping', self.mc.sounds)   # .wav
        self.assertIn('264828_text', self.mc.sounds)        # .ogg
        self.assertIn('4832__zajo__drum07', self.mc.sounds)   # .wav
        self.assertIn('84480__zgump__drum-fx-4', self.mc.sounds)   # .wav
        self.assertIn('100184__menegass__rick-drum-bd-hard', self.mc.sounds)   # .wav

        # /sounds/voice
        self.assertIn('104457_moron_test', self.mc.sounds)  # .wav
        self.assertEqual(self.mc.sounds['104457_moron_test'].volume, 0.6)
        self.assertIn('113690_test', self.mc.sounds)        # .wav

        # /sounds/music
        self.assertIn('263774_music', self.mc.sounds)       # .wav

        # Sound groups
        self.assertIn('drum_group', self.mc.sounds)

        # Make sure sound has ducking (since it was specified in the config files)
        self.assertTrue(self.mc.sounds['104457_moron_test'].has_ducking)

        # Test baseline internal audio message count
        self.assertEqual(interface.get_in_use_request_message_count(), 0)
        self.assertEqual(interface.get_in_use_notification_message_count(), 0)

        # Test sound_player
        self.assertFalse(track_sfx.sound_is_playing(self.mc.sounds['264828_text']))
        self.mc.events.post('play_sound_text')
        self.mc.events.post('play_sound_music')
        self.advance_time(1)
        self.assertTrue(track_sfx.sound_is_playing(self.mc.sounds['264828_text']))

        # Test two sounds at the same time on the voice track (only
        # 1 sound at a time max).  Second sound should be queued and
        # play immediately after the first one ends.
        self.assertEqual(track_voice.get_sound_queue_count(), 0)
        self.mc.events.post('play_sound_test')
        self.advance_time()

        # Make sure first sound is playing on the voice track
        self.assertEqual(track_voice.get_status()[0]['sound_id'], self.mc.sounds['113690_test'].id)
        self.mc.events.post('play_sound_moron_test')
        self.advance_time()

        # Make sure first sound is still playing and the second one has been queued
        self.assertEqual(track_voice.get_status()[0]['sound_id'], self.mc.sounds['113690_test'].id)
        self.assertEqual(track_voice.get_sound_queue_count(), 1)
        self.assertTrue(track_voice.sound_is_in_queue(self.mc.sounds['104457_moron_test']))
        self.advance_time(0.1)

        # Now stop sound that is not yet playing but is queued (should be removed from queue)
        self.mc.events.post('stop_sound_moron_test')
        self.advance_time(0.25)
        self.assertFalse(track_voice.sound_is_in_queue(self.mc.sounds['104457_moron_test']))

        # Play moron test sound again (should be added to queue)
        self.mc.events.post('play_sound_moron_test')
        self.advance_time(0.1)
        self.assertTrue(track_voice.sound_is_in_queue(self.mc.sounds['104457_moron_test']))

        # Make sure text sound is still playing (looping)
        self.assertTrue(track_sfx.sound_is_playing(self.mc.sounds['264828_text']))

        # Ensure sound.events_when_looping is working properly (send event when a sound loops)
        self.mc.bcp_processor.send.assert_any_call('trigger', name='text_sound_looping')

        # Send an event to stop the text sound looping
        self.mc.events.post('stop_sound_looping_text')
        self.advance_time(2)

        # Text sound should no longer be playing
        self.assertFalse(track_sfx.sound_is_playing(self.mc.sounds['264828_text']))

        self.advance_time(2.7)
        self.mc.events.post('play_sound_synthping')
        self.advance_time(3)
        self.assertEqual(track_voice.get_status()[0]['sound_id'], self.mc.sounds['104457_moron_test'].id)
        self.assertEqual(track_voice.get_status()[0]['volume'], 76)
        self.mc.events.post('play_sound_synthping')
        self.advance_time(6)
        self.mc.events.post('stop_sound_music')
        self.mc.events.post('play_sound_synthping_in_mode')
        self.advance_time(1)
        self.mc.events.post('play_sound_synthping')
        self.advance_time(1)

        # Test playing sound pool (many times)
        for x in range(16):
            self.mc.events.post('play_sound_drum_group')
            self.advance_time(0.1)

        self.mc.events.post('play_sound_drum_group_in_mode')
        self.advance_time(1)

        # Test stopping the mode
        self.send(bcp_command='mode_stop', name='mode1')
        self.advance_time(1)

        # Test sound events
        self.mc.bcp_processor.send.assert_any_call('trigger', name='moron_test_played')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='moron_test_stopped')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='synthping_played')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='moron_marker')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='moron_next_marker')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='last_marker')

        # Check for internal sound message processing leaks (are there any internal sound
        # events that get generated, but never processed and cleared from the queue?)
        self.assertEqual(interface.get_in_use_request_message_count(), 0)
        self.assertEqual(interface.get_in_use_notification_message_count(), 0)

    def test_mode_sounds(self):
        """ Test the sound system using sounds specified in a mode """

        if SoundSystem is None:
            log = logging.getLogger('TestAudio')
            log.warning("Sound system is not enabled - skipping audio tests")
            self.skipTest("Sound system is not enabled")

        self.assertIsNotNone(self.mc.sound_system)
        interface = self.mc.sound_system.audio_interface
        self.assertIsNotNone(interface)

        self.assertTrue(self.mc, 'sounds')

        # Mock BCP send method
        self.mc.bcp_processor.send = MagicMock()

        # Allow some time for sound assets to load
        self.advance_time(2)

        # Start mode
        self.send(bcp_command='mode_start', name='mode2', priority=500)
        self.assertTrue(self.mc.modes['mode2'].active)
        self.assertEqual(self.mc.modes['mode2'].priority, 500)
        self.assertIn('boing_mode2', self.mc.sounds)  # .wav

        self.advance_time(1)

        self.mc.events.post('play_sound_boing_in_mode2')
        self.advance_time(1)

    def test_sound_fading(self):
        """ Tests the fading of sounds"""

        if SoundSystem is None:
            log = logging.getLogger('TestAudio')
            log.warning("Sound system is not enabled - skipping audio tests")
            self.skipTest("Sound system is not enabled")

        self.assertIsNotNone(self.mc.sound_system)
        interface = self.mc.sound_system.audio_interface
        self.assertIsNotNone(interface)

        track_music = interface.get_track_by_name("music")
        self.assertIsNotNone(track_music)
        self.assertEqual(track_music.name, "music")
        self.assertEqual(track_music.max_simultaneous_sounds, 1)

        self.advance_time(2)

        self.assertIn('263774_music', self.mc.sounds)       # .wav
        music = self.mc.sounds['263774_music']
        retry_count = 10
        while not music.loaded and retry_count > 0:
            if not music.loading:
                music.load()
            self.advance_time(0.5)
            retry_count -= 1

        self.assertTrue(music.loaded)
        instance1 = music.play({'fade_in': 2.0, 'volume': 1.0})
        self.advance_time()

        status = track_music.get_status()
        self.assertEqual(status[0]['sound_instance_id'], instance1.id)
        self.assertEqual(status[0]['status'], "playing")
        self.assertEqual(status[0]['fading_status'], "fade in")
        self.advance_time(2)

        instance1.stop(1)
        self.advance_time()
        status = track_music.get_status()
        self.assertEqual(status[0]['status'], "stopping")
        self.assertEqual(status[0]['fading_status'], "fade out")
        self.advance_time(1)
        status = track_music.get_status()
        self.assertEqual(status[0]['status'], "idle")

        instance2 = music.play({'fade_in': 0, 'volume': 1.0})
        self.advance_time(1)

        status = track_music.get_status()
        self.assertEqual(status[0]['sound_instance_id'], instance2.id)
        self.assertEqual(status[0]['status'], "playing")
        self.assertEqual(status[0]['fading_status'], "not fading")

        instance2.stop(0)
        self.advance_time(0.5)
        status = track_music.get_status()
        self.assertEqual(status[0]['status'], "idle")

    def test_sound_start_at(self):
        """ Tests starting a sound at a position other than the beginning"""

        if SoundSystem is None:
            log = logging.getLogger('TestAudio')
            log.warning("Sound system is not enabled - skipping audio tests")
            self.skipTest("Sound system is not enabled")

        self.assertIsNotNone(self.mc.sound_system)
        interface = self.mc.sound_system.audio_interface
        self.assertIsNotNone(interface)

        track_music = interface.get_track_by_name("music")
        self.assertIsNotNone(track_music)
        self.assertEqual(track_music.name, "music")
        self.assertEqual(track_music.max_simultaneous_sounds, 1)

        self.advance_time(1)

        self.assertIn('263774_music', self.mc.sounds)  # .wav

        settings = {'start_at': 7.382}
        instance = self.mc.sounds['263774_music'].play(settings)
        self.advance_time()
        status = track_music.get_status()
        self.assertGreater(status[0]['sample_pos'], interface.convert_seconds_to_buffer_length(7.382))
        self.advance_time(1)
        instance.stop(0.25)
        self.advance_time(0.3)

    def test_sound_instance_management(self):
        """ Tests instance management of sounds"""

        if SoundSystem is None:
            log = logging.getLogger('TestAudio')
            log.warning("Sound system is not enabled - skipping audio tests")
            self.skipTest("Sound system is not enabled")

        self.assertIsNotNone(self.mc.sound_system)
        interface = self.mc.sound_system.audio_interface
        self.assertIsNotNone(interface)

        # Mock BCP send method
        self.mc.bcp_processor.send = MagicMock()

        track_sfx = interface.get_track_by_name("sfx")
        self.assertIsNotNone(track_sfx)
        self.assertEqual(track_sfx.name, "sfx")
        self.assertEqual(track_sfx.max_simultaneous_sounds, 8)
        self.advance_time()

        # Test skip stealing method
        self.assertIn('264828_text', self.mc.sounds)  # .wav
        text_sound = self.mc.sounds['264828_text']
        if not text_sound.loaded:
            if not text_sound.loading:
                text_sound.load()
            self.advance_time(1)
            
        self.assertEqual(text_sound.max_instances, 3)
        if SoundStealingMethod is not None:
            self.assertEqual(text_sound.stealing_method, SoundStealingMethod.skip)

        instance1 = text_sound.play({'loops': 0, 'events_when_played': ['instance1_played']})
        instance2 = text_sound.play({'loops': 0, 'events_when_played': ['instance2_played']})
        instance3 = text_sound.play({'loops': 0, 'events_when_played': ['instance3_played']})
        instance4 = text_sound.play({'loops': 0, 'events_when_played': ['instance4_played']})
        instance5 = text_sound.play({'loops': 0, 'events_when_played': ['instance5_played']})

        self.advance_time(0.5)

        self.mc.bcp_processor.send.assert_any_call('trigger', name='instance1_played')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='instance2_played')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='instance3_played')
        with self.assertRaises(AssertionError):
            self.mc.bcp_processor.send.assert_any_call('trigger', name='instance4_played')
            self.mc.bcp_processor.send.assert_any_call('trigger', name='instance5_played')

        self.assertTrue(instance1.played)
        self.assertTrue(instance2.played)
        self.assertTrue(instance3.played)
        self.assertIsNone(instance4)
        self.assertIsNone(instance5)

        track_sfx.stop_all_sounds()
        self.advance_time()

        # Test oldest stealing method
        self.mc.bcp_processor.send.reset_mock()
        self.assertIn('210871_synthping', self.mc.sounds)  # .wav
        synthping = self.mc.sounds['210871_synthping']
        if not synthping.loaded:
            if not synthping.loading:
                synthping.load()
            self.advance_time(1)
        self.assertEqual(synthping.max_instances, 3)
        if SoundStealingMethod is not None:
            self.assertEqual(synthping.stealing_method, SoundStealingMethod.oldest)

        synthping_instance1 = synthping.play(
            {'events_when_played': ['synthping_instance1_played'],
             'events_when_stopped': ['synthping_instance1_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='synthping_instance1_played')])

        synthping_instance2 = synthping.play(
            {'events_when_played': ['synthping_instance2_played'],
             'events_when_stopped': ['synthping_instance2_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='synthping_instance1_played'),
                                                     call('trigger', name='synthping_instance2_played')])

        synthping_instance3 = synthping.play(
            {'events_when_played': ['synthping_instance3_played'],
             'events_when_stopped': ['synthping_instance3_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='synthping_instance1_played'),
                                                     call('trigger', name='synthping_instance2_played'),
                                                     call('trigger', name='synthping_instance3_played')])

        synthping_instance4 = synthping.play(
            {'events_when_played': ['synthping_instance4_played'],
             'events_when_stopped': ['synthping_instance4_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='synthping_instance1_played'),
                                                     call('trigger', name='synthping_instance2_played'),
                                                     call('trigger', name='synthping_instance3_played'),
                                                     call('trigger', name='synthping_instance1_stopped'),
                                                     call('trigger', name='synthping_instance4_played')])

        synthping_instance5 = synthping.play(
            {'events_when_played': ['synthping_instance5_played'],
             'events_when_stopped': ['synthping_instance5_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='synthping_instance1_played'),
                                                     call('trigger', name='synthping_instance2_played'),
                                                     call('trigger', name='synthping_instance3_played'),
                                                     call('trigger', name='synthping_instance1_stopped'),
                                                     call('trigger', name='synthping_instance4_played'),
                                                     call('trigger', name='synthping_instance2_stopped'),
                                                     call('trigger', name='synthping_instance5_played')])

        self.assertTrue(synthping_instance1.played)
        self.assertTrue(synthping_instance2.played)
        self.assertTrue(synthping_instance3.played)
        self.assertTrue(synthping_instance4.played)
        self.assertTrue(synthping_instance5.played)

        track_sfx.stop_all_sounds()
        self.advance_time()

        # Test newest stealing method
        self.mc.bcp_processor.send.reset_mock()
        self.assertIn('198361_sfx-028', self.mc.sounds)  # .wav
        sfx = self.mc.sounds['198361_sfx-028']
        if not sfx.loaded:
            if not sfx.loading:
                sfx.load()
            self.advance_time(1)
        self.assertEqual(sfx.max_instances, 3)
        if SoundStealingMethod is not None:
            self.assertEqual(sfx.stealing_method, SoundStealingMethod.newest)


        sfx_instance1 = sfx.play(
            {'events_when_played': ['sfx_instance1_played'],
             'events_when_stopped': ['sfx_instance1_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='sfx_instance1_played')])

        sfx_instance2 = sfx.play(
            {'events_when_played': ['sfx_instance2_played'],
             'events_when_stopped': ['sfx_instance2_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='sfx_instance1_played'),
                                                     call('trigger', name='sfx_instance2_played')])

        sfx_instance3 = sfx.play(
            {'events_when_played': ['sfx_instance3_played'],
             'events_when_stopped': ['sfx_instance3_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='sfx_instance1_played'),
                                                     call('trigger', name='sfx_instance2_played'),
                                                     call('trigger', name='sfx_instance3_played')])

        sfx_instance4 = sfx.play(
            {'events_when_played': ['sfx_instance4_played'],
             'events_when_stopped': ['sfx_instance4_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='sfx_instance1_played'),
                                                     call('trigger', name='sfx_instance2_played'),
                                                     call('trigger', name='sfx_instance3_played'),
                                                     call('trigger', name='sfx_instance3_stopped'),
                                                     call('trigger', name='sfx_instance4_played')])

        sfx_instance5 = sfx.play(
            {'events_when_played': ['sfx_instance5_played'],
             'events_when_stopped': ['sfx_instance5_stopped']})
        self.advance_time()
        self.mc.bcp_processor.send.assert_has_calls([call('trigger', name='sfx_instance1_played'),
                                                     call('trigger', name='sfx_instance2_played'),
                                                     call('trigger', name='sfx_instance3_played'),
                                                     call('trigger', name='sfx_instance3_stopped'),
                                                     call('trigger', name='sfx_instance4_played'),
                                                     call('trigger', name='sfx_instance4_stopped'),
                                                     call('trigger', name='sfx_instance5_played')])

        self.assertTrue(sfx_instance1.played)
        self.assertTrue(sfx_instance2.played)
        self.assertTrue(sfx_instance3.played)
        self.assertTrue(sfx_instance4.played)
        self.assertTrue(sfx_instance5.played)

        # Stop all sounds playing on the sfx track to start the next test
        track_sfx.stop_all_sounds()
        self.advance_time()
        self.mc.bcp_processor.send.reset_mock()
        self.assertEqual(track_sfx.get_sound_players_in_use_count(), 0)
        self.assertEqual(track_sfx.get_sound_queue_count(), 0)

        # Test max_instances in sound group (skip stealing method)
        self.assertIn('drum_group', self.mc.sounds)
        drum_group = self.mc.sounds['drum_group']
        self.assertEqual(drum_group.max_instances, 3)
        if SoundStealingMethod is not None:
            self.assertEqual(drum_group.stealing_method, SoundStealingMethod.skip)

        drum_group_instance1 = drum_group.play({'events_when_played': ['drum_group_instance1_played']})
        drum_group_instance2 = drum_group.play({'events_when_played': ['drum_group_instance2_played']})
        drum_group_instance3 = drum_group.play({'events_when_played': ['drum_group_instance3_played']})
        drum_group_instance4 = drum_group.play({'events_when_played': ['drum_group_instance4_played']})
        drum_group_instance5 = drum_group.play({'events_when_played': ['drum_group_instance5_played']})
        self.advance_time()

        self.mc.bcp_processor.send.assert_any_call('trigger', name='drum_group_instance1_played')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='drum_group_instance2_played')
        self.mc.bcp_processor.send.assert_any_call('trigger', name='drum_group_instance3_played')
        with self.assertRaises(AssertionError):
            self.mc.bcp_processor.send.assert_any_call('trigger', name='drum_group_instance4_played')
            self.mc.bcp_processor.send.assert_any_call('trigger', name='drum_group_instance5_played')

        self.assertTrue(drum_group_instance1.played)
        self.assertTrue(drum_group_instance2.played)
        self.assertTrue(drum_group_instance3.played)
        self.assertIsNone(drum_group_instance4)
        self.assertIsNone(drum_group_instance5)

        """
        # Add another track with the same name (should not be allowed)
        # Add another track with the same name, but different casing (should not be allowed)
        # Attempt to create track with max_simultaneous_sounds > 32 (the current max)
        # Attempt to create track with max_simultaneous_sounds < 1 (the current max)
        # Add up to the maximum number of tracks allowed
        # There should now be the maximum number of tracks allowed
        # Try to add another track (more than the maximum allowed)

        # TODO: Tests to write:
        # Load sounds (wav, ogg, flac, unsupported format)
        # Play a sound
        # Play two sounds on track with max_simultaneous_sounds = 1 (test sound queue,
        time expiration, priority scenarios)
        # Play a sound on each track simultaneously
        # Stop all sounds on track
        # Stop all sounds on all tracks
        # Ducking
        # Configuration file tests (audio interface, tracks, sounds, sound player, sound
        # trigger events, etc.)
        #
        """
