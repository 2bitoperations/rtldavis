import logging
import asyncio
from typing import Callable, Any, Coroutine

try:
    from gpiozero import Button
except ImportError:
    Button = None

logger = logging.getLogger(__name__)


def init_buttons(
    loop: asyncio.AbstractEventLoop, 
    broadcast_func: Callable[[str, Any], Coroutine[Any, Any, None]]
):
    """
    Initializes the 5-way switch on the designated GPIO pins and registers
    callbacks that bridge the gpiozero background C-threads securely into the 
    main asyncio event loop.
    """
    if Button is None:
        logger.error("gpiozero is not installed. Buttons will not work.")
        return

    buttons = {
        "up": 5,
        "right": 19,
        "left": 13,
        "down": 6,
        "click": 26,
    }

    def on_press(btn_name: str):
        logger.info(f"Button pressed: {btn_name}")
        payload = {"action": "press", "button": btn_name}
        # Safely inject the async broadcast function back onto the main event loop
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(broadcast_func("button", payload))
        )

    def on_release(btn_name: str):
        logger.info(f"Button released: {btn_name}")
        payload = {"action": "release", "button": btn_name}
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(broadcast_func("button", payload))
        )

    try:
        # We must keep references to the Button objects so python's garbage collector 
        # doesn't destroy them and unregister the hardware interrupts.
        active_buttons = []
        for name, pin in buttons.items():
            # The Pi internal pull-up matches the user's wiring diagram (switching to GND)
            b = Button(pin, pull_up=True)
            
            # Use default arguments to capture the current iteration's value in the closure
            b.when_pressed = lambda n=name: on_press(n)
            b.when_released = lambda n=name: on_release(n)
            
            active_buttons.append(b)
        
        # Attach list to the event loop just to keep them alive for the duration of the app
        loop._rtldavis_buttons = active_buttons
        logger.warning(f"Initialized 5-way switch on GPIO pins {list(buttons.values())}")
        
    except Exception as e:
        logger.error(f"Failed to initialize GPIO buttons: {e}")
