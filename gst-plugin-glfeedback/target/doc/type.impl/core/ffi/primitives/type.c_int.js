(function() {
    var type_impls = Object.fromEntries([["gio_sys",[]],["glib_sys",[]],["gstreamer_base_sys",[]],["gstreamer_gl_sys",[]],["gstreamer_sys",[]],["gstreamer_video_sys",[]]]);
    if (window.register_type_impls) {
        window.register_type_impls(type_impls);
    } else {
        window.pending_type_impls = type_impls;
    }
})()
//{"start":55,"fragment_lengths":[14,16,26,24,21,27]}