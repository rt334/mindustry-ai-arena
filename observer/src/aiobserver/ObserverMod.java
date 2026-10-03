package aiobserver;

import arc.Core;
import arc.Events;
import arc.Input;
import arc.graphics.Color;
import arc.input.KeyCode;
import arc.math.Mathf;
import arc.scene.ui.Label;
import arc.scene.ui.layout.Table;
import arc.util.Time;
import mindustry.Vars;
import mindustry.game.EventType;
import mindustry.game.Team;
import mindustry.gen.Groups;
import mindustry.gen.Unit;
import mindustry.mod.Mod;
import mindustry.ui.Styles;

/**
 * AI 竞技场 · 观战端。
 *
 * 设计目标（DESIGN.md P5）：人能看直播。
 *
 * 关键约束：**只读**。
 *   观察者不进任何战斗队伍、不生成单位、不执行任何写操作。
 *   它只是把相机解放出来，让操作者能在世界里自由飞行。
 *
 * 为什么不做「裁判走引擎实体同步」：
 *   引擎的 writeCustomEntitySnapshot 与 hiddenIds 机制会打架（先删后建导致闪烁）。
 *   因此观战数据一律走 HTTP（AI 竞技场的 /map /units /buildings 端点），
 *   本 Mod 只负责相机与交互，不碰实体同步。
 *
 * 操作：
 *   WASD / 方向键   平移
 *   中键拖拽         平移
 *   滚轮             缩放
 *   空格             停住相机（暂停跟随）
 *   Tab              在存活队伍间循环跳转
 *   F1               显示/隐藏帮助
 */
public class ObserverMod extends Mod {

    private static final float PAN_SPEED = 12f;      // 格/秒
    private static final float ZOOM_STEP = 0.15f;

    private boolean enabled = true;
    private boolean freeCamera = false;
    private int viewTeamIndex = 0;
    private Label statusLabel;
    private Table helpTable;
    private boolean helpVisible = true;

    private float lastDragX, lastDragY;
    private boolean dragging = false;

    @Override
    public void init() {
        Events.on(EventType.ClientLoadEvent.class, e -> Core.app.post(this::setupUI));

        // 每帧推进相机。放在 update 里而不是监听器里，是因为需要持续响应按键。
        Events.run(EventType.Trigger.update, this::updateCamera);
    }

    // ---------------------------------------------------------------- ui

    private void setupUI() {
        if (Vars.ui == null || Vars.ui.hudGroup == null) return;

        Table root = new Table();
        root.setFillParent(true);
        root.top().left();

        Table box = new Table();
        box.background(Styles.black6);

        statusLabel = box.label(this::statusText).left().pad(4f).get();
        box.row();
        box.table(btns -> {
            btns.defaults().pad(2f);
            btns.button("自由相机", Styles.defaultt, () -> {
                freeCamera = !freeCamera;
                if (freeCamera) detachCamera();
            }).width(110f);
            btns.button("下一队", Styles.defaultt, this::cycleTeam).width(90f);
            btns.button("帮助", Styles.defaultt, () -> {
                helpVisible = !helpVisible;
                if (helpTable != null) helpTable.visible = helpVisible;
            }).width(70f);
        }).left().row();

        helpTable = new Table();
        helpTable.background(Styles.black6);
        helpTable.add("[accent]观战操作[]").left().row();
        helpTable.add("WASD / 方向键   平移相机").left().row();
        helpTable.add("中键拖拽         平移相机").left().row();
        helpTable.add("滚轮             缩放").left().row();
        helpTable.add("Tab              切换队伍视角").left().row();
        helpTable.add("F1               显示/隐藏本帮助").left().row();
        helpTable.add("[lightgray]本 Mod 只读：不生成单位、不参与战斗[]").left().row();
        box.add(helpTable).left().padTop(4f);

        root.add(box).left().top().pad(8f);

        Vars.ui.hudGroup.addChild(root);
    }

    private String statusText() {
        StringBuilder sb = new StringBuilder();
        sb.append("[accent]观战端[]  ");
        sb.append(freeCamera ? "[green]自由相机[]" : "[gray]跟随[]");
        sb.append("  队伍: ").append(currentTeamName());
        return sb.toString();
    }

    private String currentTeamName() {
        var teams = activeTeams();
        if (teams.isEmpty()) return "-";
        int i = Mathf.clamp(viewTeamIndex, 0, teams.size - 1);
        return teams.get(i).name;
    }

    private arc.struct.Seq<Team> activeTeams() {
        arc.struct.Seq<Team> out = new arc.struct.Seq<>();
        if (Vars.state == null) return out;
        for (var td : Vars.state.teams.present) {
            if (td.cores.size > 0) out.add(td.team);
        }
        return out;
    }

    // ---------------------------------------------------------------- camera

    private void detachCamera() {
        // 把相机从玩家单位上摘下来 —— 设为自由位置后引擎不再每帧拉回
        Core.camera.position.set(Core.camera.position);
    }

    private void cycleTeam() {
        var teams = activeTeams();
        if (teams.isEmpty()) return;
        viewTeamIndex = (viewTeamIndex + 1) % teams.size;
        jumpTo(teams.get(viewTeamIndex));
    }

    /** 跳到指定队伍的核心位置。 */
    private void jumpTo(Team team) {
        var core = team.core();
        if (core != null) {
            Core.camera.position.set(core.x, core.y);
            freeCamera = true;
            detachCamera();
            return;
        }
        // 没有核心就跳到该队第一个单位
        for (Unit u : Groups.unit) {
            if (u.team == team) {
                Core.camera.position.set(u.x, u.y);
                freeCamera = true;
                detachCamera();
                return;
            }
        }
    }

    private void updateCamera() {
        if (!enabled || Vars.state == null || !Vars.state.isPlaying()) return;
        if (Vars.ui != null && Vars.ui.chatfrag != null && Vars.ui.chatfrag.shown()) return;

        Input input = Core.input;

        // F1 切换帮助
        if (input.keyTap(KeyCode.f1)) {
            helpVisible = !helpVisible;
            if (helpTable != null) helpTable.visible = helpVisible;
        }

        // Tab 循环队伍
        if (input.keyTap(KeyCode.tab)) cycleTeam();

        // 中键拖拽。注意 arc 的鼠标坐标是方法不是字段。
        float mx = input.mouseX(), my = input.mouseY();
        if (input.keyDown(KeyCode.mouseMiddle)) {
            if (!dragging) { dragging = true; lastDragX = mx; lastDragY = my; }
            float dx = mx - lastDragX;
            float dy = my - lastDragY;
            lastDragX = mx;
            lastDragY = my;
            // 屏幕像素换算成世界位移。除以显示缩放让不同分辨率下手感一致。
            float k = 1f / Vars.renderer.getDisplayScale();
            Core.camera.position.x -= dx * k;
            Core.camera.position.y += dy * k;
            freeCamera = true;
        } else {
            dragging = false;
        }

        // 滚轮缩放 —— 复用引擎自己的缩放入口，保证范围限制与玩家操作一致
        float scroll = input.axisTap(mindustry.input.Binding.zoom);
        if (Math.abs(scroll) > 0f) {
            Vars.renderer.scaleCamera(scroll);
        }

        // WASD / 方向键平移
        float ax = 0f, ay = 0f;
        if (input.keyDown(KeyCode.a) || input.keyDown(KeyCode.left))  ax -= 1f;
        if (input.keyDown(KeyCode.d) || input.keyDown(KeyCode.right)) ax += 1f;
        if (input.keyDown(KeyCode.s) || input.keyDown(KeyCode.down))  ay -= 1f;
        if (input.keyDown(KeyCode.w) || input.keyDown(KeyCode.up))    ay += 1f;

        if (ax != 0f || ay != 0f) {
            float speed = PAN_SPEED * Vars.tilesize * Time.delta;
            Core.camera.position.x += ax * speed;
            Core.camera.position.y += ay * speed;
            freeCamera = true;
        }
    }

    /** 供外部（其他 Mod / 调试）启停。 */
    public void setEnabled(boolean v) { this.enabled = v; }
}
