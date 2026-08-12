"""Boot entry point: draw the whole ePaper ticket once."""

import epaper_ticket

epaper_ticket.blink(1, 500, 100)
try:
    print(epaper_ticket.show_new_serial())
    epaper_ticket.blink(3)
except Exception as error:
    import sys
    with open("epaper-error.txt", "w") as error_file:
        sys.print_exception(error, error_file)
    epaper_ticket.blink(10, 80, 80)
    raise
