from thermalright_lcd.output_mode import OutputMode, OutputOwnership


def test_one_final_frame_producer_per_display():
    owner = OutputOwnership()
    media = owner.transition(OutputMode.MEDIA)
    assert owner.accepts(media, OutputMode.MEDIA)
    monitor = owner.transition(OutputMode.HARDWARE_MONITOR)
    assert not owner.accepts(media, OutputMode.MEDIA)
    assert owner.accepts(monitor, OutputMode.HARDWARE_MONITOR)


def test_transition_invalidates_in_flight_prepared_frame():
    owner = OutputOwnership()
    old = owner.transition(OutputMode.HARDWARE_MONITOR)
    owner.transition(OutputMode.MEDIA)
    owner.transition(OutputMode.HARDWARE_MONITOR)
    assert not owner.accepts(old, OutputMode.HARDWARE_MONITOR)


def test_repeated_same_mode_does_not_invalidate_current_work():
    owner = OutputOwnership()
    lease = owner.transition(OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
    same = owner.transition(OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
    assert same == lease
    assert owner.accepts(lease, OutputMode.MEDIA_WITH_SENSOR_OVERLAY)


def test_twenty_switch_cycles_end_with_only_selected_owner():
    owner = OutputOwnership()
    stale = []
    for _ in range(20):
        stale.append(owner.transition(OutputMode.MEDIA))
        stale.append(owner.transition(OutputMode.HARDWARE_MONITOR))
    final = owner.transition(OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
    assert owner.accepts(final, OutputMode.MEDIA_WITH_SENSOR_OVERLAY)
    assert all(not owner.accepts(item, item.mode) for item in stale)
