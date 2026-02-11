#include "quantum.h"

// Define your custom macros or functions here
enum custom_keycodes {
  MY_CUSTOM_MACRO = SAFE_RANGE, // Start after ZSA's safe range if possible, or just use a high number
};

// This function is called by the wrapper in keymap.c
// Return false to stop processing (if you handled the key)
// Return true to let Oryx handle the key
bool process_record_user_custom(uint16_t keycode, keyrecord_t *record) {
  switch (keycode) {
    // Example:
    // case KC_A:
    //   if (record->event.pressed) {
    //     SEND_STRING("Hello World");
    //     return false; // Stop Oryx from sending 'a'
    //   }
    //   return true;
  }
  return true;
}

// Add other hooks here if needed (led_update_user_custom, etc.)
