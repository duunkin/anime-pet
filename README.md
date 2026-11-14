# Anime Desktop Pet

A Python-based desktop pet application featuring Live2D anime characters that walk around your screen, react to mouse interactions, and provide companionship.

![Phase](https://img.shields.io/badge/Phase-1%20In%20Progress-yellow)
![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%2F%20Linux-lightgrey)

## Features

### Current Features (Phase 1)
- **Live2D Character Rendering**: High-quality anime character display using Live2D Cubism SDK
- **Small Window Overlay**: Performance-optimized small window (character + 40px margin) instead of fullscreen overlay
- **Physics Simulation**: Gravity, falling, and ground collision detection
- **Mouse Interactions**:
  - Eyes follow cursor globally (even when cursor is outside the window)
  - Left-click: Startled reaction
  - Left-click + drag: Lift and move character; release to fall with gravity
  - Right-click: Context menu (Sleep, Dance, Exit)
  - Click-through: Transparent areas (40px margin) allow clicks to pass through to apps below
- **State Machine**: Manages character behaviors (IDLE, DRAGGED, FALLING, STARTLED, SLEEPING, ACTION)
- **Adaptive FPS**: 60 FPS during activity, 15 FPS when idle to save power
- **Shaped Hit-Testing**: Accurate mouse detection (70% width for head, 100% for body)
- **Per-Monitor DPI Awareness v2**: Proper scaling on high-DPI displays
- **Character Loading**: Automatic character discovery from `characters/` directory

### Planned Features (Future Phases)
- Multi-monitor support with character movement between screens
- Window edge climbing and standing on window title bars
- Fullscreen app detection (auto-hide during gaming/presentations)
- System tray integration with settings
- Auto-start with OS
- CPU/RAM monitoring with character reactions
- Window/app title awareness for context-aware behavior
- Keyboard activity detection (encouragement when typing, sleep when idle)
- Multiple character interactions
- Affection and mood systems
- Local AI chat (1-3B parameter models running offline)
- UI chat window with hotkey toggle
- Reminder system (rest, water, study deadlines)
- Character addition/removal in-app
- Persistence (save position, mood, affection)
- Windows (.exe) and Linux (AppImage) builds

## Requirements

### Operating System
- Windows 10/11 (primary target)
- Linux (planned support)

### Python Dependencies
- Python 3.8 or higher
- PySide6 (Qt6 for Python)
- live2d-py (Live2D Cubism SDK Python bindings)
- PyOpenGL

### System Requirements
- OpenGL 3.3+ compatible GPU
- ~50MB disk space per character

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/duunkin/anime-pet.git
cd anime-pet
```

### 2. Create Virtual Environment
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On Linux/Mac
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

Note: Create a `requirements.txt` file with:
```
PySide6>=6.0.0
live2d-py>=0.1.0
PyOpenGL>=3.1.0
```

### 4. Add Characters
Place Live2D character folders in the `characters/` directory. Each character should have:
- `<CharacterName>.model3.json` (Live2D model file)
- `character.json` (optional configuration)
- Motion files in `motions/` subdirectory
- Expression files in `expressions/` subdirectory

Default characters included: Haru, Hiyori, Mao, Mark, Natori, Ren, Rice, Wanko

## Usage

### Running the Application
```bash
python src/main.py
```

### Command-Line Options
```bash
python src/main.py --character Hiyori    # Specify character
python src/main.py --auto-exit 30       # Auto-exit after 30 seconds (for testing)
```

### Keyboard Shortcuts
- `Esc` or `Ctrl+Q`: Exit application

### Mouse Interactions
- **Move cursor near character**: Eyes follow cursor
- **Left-click**: Character gets startled
- **Left-click + drag**: Lift and move character; release to drop
- **Right-click**: Open context menu
  - Sleep: Character goes to sleep
  - Dance: Character performs dance animation
  - Exit: Close application

### Click-Through Behavior
The overlay window has a 40px transparent margin on all sides. Clicks in these areas pass through to the application below, allowing normal workflow. Only clicks on the character body are captured.

## Configuration

### Character Configuration (`characters/<name>/character.json`)

```json
{
  "name": "Hiyori",
  "model3_path": "Hiyori.model3.json",
  "scale": 0.65,
  "motion_map": {
    "idle": "Idle",
    "startled": "TapBody",
    "sleep": "motions/Hiyori_m08.motion3.json",
    "dance": "motions/Hiyori_m05.motion3.json",
    "dragged": "motions/Hiyori_m02.motion3.json"
  },
  "expression_map": {}
}
```

**Fields:**
- `name`: Character display name
- `model3_path`: Path to Live2D model file (relative to character directory)
- `scale`: Display scale factor (default: 0.65)
- `motion_map`: Maps behavior names to motion group names or file paths
- `expression_map`: Maps behavior names to expression names

### Application Settings (`src/config/settings.py`)

Key configurable parameters:
- `target_fps`: 60 (active FPS)
- `idle_fps`: 15 (idle FPS for power saving)
- `fps_idle_timeout_sec`: 6.0 (seconds before FPS drops)
- `window_margin_px`: 40 (margin around character in pixels)
- `character_height_px`: 480.0 (default character height)
- `gravity`: 2400.0 (pixels/s²)
- `eye_tracking_distance_px`: 500.0 (cursor distance for eye tracking)
- `cursor_poll_interval_ms`: 30 (mouse polling interval)

## Architecture

### Module Structure

```
anime-pet/
├── src/
│   ├── main.py                 # Application entry point
│   ├── config/
│   │   └── settings.py         # Configuration management
│   ├── core/
│   │   ├── character.py        # Character profile and behavior mapping
│   │   └── physics.py          # Physics simulation (gravity, collision)
│   ├── behavior/
│   │   └── state_machine.py    # State machine for character behavior
│   └── render/
│       ├── live2d_view.py      # Live2D rendering and eye tracking
│       └── overlay.py          # Qt overlay window and mouse handling
├── characters/                 # Live2D character folders
│   ├── Hiyori/
│   ├── Haru/
│   └── ...
├── tests/
│   └── spikes/                 # Technical spike tests
└── GEMINI.md                   # Developer documentation (Vietnamese)
```

### Key Components

**PetPhysics** (`src/core/physics.py`)
- Manages character position, velocity, and gravity
- All coordinates in Logical Pixels (DPI-aware)
- Handles drag-and-drop and ground collision
- Independent of UI layer for testability

**PetStateMachine** (`src/behavior/state_machine.py`)
- Finite state machine for character behaviors
- States: IDLE, DRAGGED, FALLING, STARTLED, SLEEPING, ACTION
- Manages adaptive FPS (60/15 FPS switching)
- Triggers random idle actions every 8-16 seconds

**Live2DView** (`src/render/live2d_view.py`)
- Live2D model loading and rendering
- Layout management with precise 40px margins
- Eye tracking with smooth interpolation
- Hit-box calculation for shaped click detection
- Behavior mapping (motion/expression triggers)

**Live2DPetOverlay** (`src/render/overlay.py`)
- Qt OpenGL widget for window management
- Small window architecture (character + margin)
- Window position sync with physics coordinates
- Dynamic click-through (WS_EX_TRANSPARENT)
- Mouse polling and shaped hit-testing
- Windows DWM transparency support

### Coordinate Systems

The application uses multiple coordinate systems:

1. **Logical Pixels** (Qt Widget coordinates)
   - Used by PetPhysics for all calculations
   - Matches DPI-aware Qt coordinate system
   - Screen coordinates for window positioning

2. **Physical Pixels** (OpenGL Framebuffer)
   - Used by Live2D rendering
   - Physical = Logical × DevicePixelRatio
   - Calculated in `setup_layout()` and `poll_cursor()`

3. **Model Space** (Live2D NDC)
   - Normalized device coordinates [-1, 1]
   - Used internally by Live2D SDK
   - Converted from physical pixels in rendering

All coordinate conversions are clearly documented in the code with DPI notes.

## Character Setup

### Adding a New Character

1. Create a folder in `characters/` (e.g., `characters/NewCharacter/`)
2. Copy Live2D model files:
   - `NewCharacter.model3.json`
   - `NewCharacter.physics3.json`
   - `NewCharacter.moc3` (binary model file)
   - Texture files
   - Motion files in `motions/` subdirectory
   - Expression files in `expressions/` subdirectory

3. Create `character.json`:
```json
{
  "name": "NewCharacter",
  "model3_path": "NewCharacter.model3.json",
  "scale": 0.65,
  "motion_map": {
    "idle": "Idle",
    "startled": "TapBody",
    "sleep": "motions/NewCharacter_m01.motion3.json",
    "dance": "motions/NewCharacter_m02.motion3.json"
  },
  "expression_map": {}
}
```

4. Run with: `python src/main.py --character NewCharacter`

### Motion Mapping

The `motion_map` in `character.json` maps application behaviors to Live2D motions:

- `idle`: Idle animation (loops continuously)
- `startled`: Reaction when clicked
- `sleep`: Sleep animation
- `dance`: Dance animation
- `dragged`: Animation while being dragged

You can use:
- Motion group names (e.g., "Idle", "TapBody")
- File paths (e.g., "motions/Hiyori_m05.motion3.json")

## Development

### Running Tests
```bash
# Run technical spike tests
python tests/spikes/spike1_overlay.py
python tests/spikes/spike2_clickthrough.py
python tests/spikes/spike3_windows.py
```

### Code Conventions
- Python 3.x with type hints for public functions
- Short docstrings for complex functions
- Separation of concerns: Physics and StateMachine don't import PySide6
- OS-dependent code wrapped in abstraction layers
- No hardcoded paths; use `pathlib` and constants
- Minimal object creation per frame for performance
- Clear error handling with logging

### Developer Documentation
See `GEMINI.md` for detailed developer documentation in Vietnamese, including:
- Working rules for AI agents
- Complete file map
- Code conventions
- Roadmap phases
- Current status tracking

## Roadmap

### Phase 0: Technical Spikes ✅
- Overlay + Live2D rendering
- Click-through mechanism
- Window positioning

### Phase 1: Basic Character ✅ (In Progress)
- Main/overlay/physics/state_machine/live2d_view integration
- Minor performance optimization needed

### Phase 2: Enhanced Interactions (Planned)
- Full mouse interaction handling
- Window edge climbing
- Window title bar standing

### Phase 3: System Awareness (Planned)
- Fullscreen app detection
- CPU/RAM monitoring
- Window/app title awareness
- Keyboard activity detection

### Phase 4: Advanced Features (Planned)
- System tray integration
- Settings persistence
- Auto-start with OS
- Multi-monitor support

### Phase 5: AI & Reminders (Planned)
- Local AI chat (1-3B models)
- Chat UI with hotkey
- Reminder system
- Character personality configuration

### Phase 6: Multi-Character (Planned)
- Multiple character support
- Character interactions
- Affection and mood systems

### Phase 7: Distribution (Planned)
- Windows .exe build
- Linux AppImage build
- Installation wizard

## Troubleshooting

### Character Not Loading
- Verify `character.json` exists in character folder
- Check `model3_path` points to correct file
- Ensure all Live2D files (.moc3, textures) are present
- Check console output for error messages

### Black Background on Windows
- Ensure DWM transparency is applied (automatic in code)
- Check Windows version (Windows 10/11 required)
- Verify OpenGL 3.3+ support

### Performance Issues
- The application uses adaptive FPS (60/15 FPS)
- Small window architecture reduces GPU load
- Check if other applications are using GPU heavily
- Adjust `target_fps` and `idle_fps` in settings

### Click-Through Not Working
- Ensure WS_EX_TRANSPARENT flag is set (automatic)
- Check cursor polling is running (~30ms interval)
- Verify character hit-box is calculated correctly
- Check console for hit-testing debug output

## License

This project is licensed under the MIT License - see LICENSE file for details.

## Acknowledgments

- Live2D Cubism SDK for character rendering
- PySide6/Qt6 for GUI framework
- Default Live2D models from Live2D Cubism SDK samples

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes with clear documentation
4. Test thoroughly on Windows 10/11
5. Submit a pull request

For major changes, please open an issue first to discuss the proposed changes.

## Contact

For questions, issues, or suggestions, please open an issue on GitHub or contact the maintainer.
