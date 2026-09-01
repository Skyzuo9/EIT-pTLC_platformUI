"""离线单测: Rf 测量核心 (rf_measure)。全部合成/纯算, 无相机无 PLC。"""
import pytest
import numpy as np

cv2 = pytest.importorskip("cv2")

from eit_ptlc.controller import rf_measure


class TestToPlateUv:
    def test_corners_map_to_unit_square(self):
        bbox = {"x": 100, "y": 200, "w": 400, "h": 800}
        assert rf_measure.to_plate_uv(100, 200, bbox) == (0.0, 0.0)
        assert rf_measure.to_plate_uv(500, 1000, bbox) == (1.0, 1.0)

    def test_center_maps_to_half(self):
        bbox = {"x": 0, "y": 0, "w": 200, "h": 100}
        u, v = rf_measure.to_plate_uv(100, 50, bbox)
        assert u == pytest.approx(0.5)
        assert v == pytest.approx(0.5)

    def test_zero_size_raises(self):
        with pytest.raises(ValueError):
            rf_measure.to_plate_uv(10, 10, {"x": 0, "y": 0, "w": 0, "h": 100})


class TestMigrationAndRf:
    def test_migration_direction_negative(self):
        # origin 在 v=0.9 (板下方), 斑点在 v=0.3 (上方), 向上迁移 direction=-1 → 正
        assert rf_measure.migration(0.3, 0.9, -1) == pytest.approx(0.6)

    def test_migration_direction_positive(self):
        assert rf_measure.migration(0.7, 0.2, 1) == pytest.approx(0.5)

    def test_compute_rf_basic(self):
        spots = [
            rf_measure.SpotHit(u=0.5, v=0.3, area_frac=0.001, center_px=(0.0, 0.0)),
            rf_measure.SpotHit(u=0.5, v=0.6, area_frac=0.001, center_px=(0.0, 0.0)),
        ]
        # origin_frac=0.9 (v), d_f=0.8 (前沿到 v=0.1), direction=-1
        res = rf_measure.compute_rf(spots, origin_frac=0.9, d_f=0.8, axis="v", direction=-1)
        assert [round(r.d_s, 3) for r in res] == [0.6, 0.3]
        assert [round(r.rf, 3) for r in res] == [0.75, 0.375]
        assert [r.index for r in res] == [0, 1]

    def test_compute_rf_zero_df_gives_none(self):
        spots = [rf_measure.SpotHit(u=0.5, v=0.3, area_frac=0.001, center_px=(0.0, 0.0))]
        res = rf_measure.compute_rf(spots, origin_frac=0.9, d_f=0.0)
        assert res[0].rf is None

    def test_compute_rf_axis_u(self):
        spots = [rf_measure.SpotHit(u=0.4, v=0.5, area_frac=0.001, center_px=(0.0, 0.0))]
        res = rf_measure.compute_rf(spots, origin_frac=0.1, d_f=0.6, axis="u", direction=1)
        assert res[0].d_s == pytest.approx(0.3)
        assert res[0].rf == pytest.approx(0.5)

    def test_compute_rf_bad_axis_raises(self):
        with pytest.raises(ValueError):
            rf_measure.compute_rf([], origin_frac=0.5, d_f=0.5, axis="z")


def _synth_plate(w=400, h=600, spots_uv=((0.3, 0.4), (0.6, 0.7))):
    """造一张 UV 风格合成图: 亮绿底 + 暗斑。返回 (image_bgr, plate_bbox)。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 1] = 200  # 绿底 (BGR 的 G 通道)
    r = 12
    for (u, v) in spots_uv:
        cx, cy = int(u * w), int(v * h)
        cv2.circle(img, (cx, cy), r, (0, 40, 0), -1)  # 暗斑
    bbox = {"x": 0, "y": 0, "w": w, "h": h}
    return img, bbox


class TestDetectSpots:
    def test_recovers_known_spots(self):
        img, bbox = _synth_plate(spots_uv=((0.3, 0.4), (0.6, 0.7)))
        hits = rf_measure.detect_spots(img, bbox)
        assert len(hits) == 2
        found = sorted((round(h.u, 1), round(h.v, 1)) for h in hits)
        assert found == [(0.3, 0.4), (0.6, 0.7)]

    def test_area_filter_rejects_tiny_noise(self):
        img, bbox = _synth_plate(spots_uv=((0.5, 0.5),))
        # 3x3 暗块: 存活 3x3 形态学开, 但面积占比 9/240000≈3.75e-5 < min_area_frac(1e-4)
        # → 必须被"面积过滤"拒掉 (而非被形态学腐蚀掉), 才真正隔离该过滤器
        img[8:11, 8:11] = (0, 40, 0)
        hits = rf_measure.detect_spots(img, bbox)
        assert len(hits) == 1
        assert hits[0].u == pytest.approx(0.5, abs=0.05)

    def test_center_px_absolute(self):
        img, bbox = _synth_plate(w=400, h=600, spots_uv=((0.5, 0.5),))
        hits = rf_measure.detect_spots(img, bbox)
        cx, cy = hits[0].center_px
        assert cx == pytest.approx(200, abs=6)
        assert cy == pytest.approx(300, abs=6)


class TestAnalyzeRf:
    def test_end_to_end_two_spots_sorted(self):
        # v=0.4 与 v=0.7; origin_frac=0.9, direction=-1 → d_s = 0.5 与 0.2
        # 期望按 d_s 升序: 先 0.2 (v=0.7), 后 0.5 (v=0.4)
        img, bbox = _synth_plate(spots_uv=((0.5, 0.4), (0.5, 0.7)))
        res = rf_measure.analyze_rf(
            img, bbox, origin_frac=0.9, d_f=0.8, axis="v", direction=-1,
        )
        assert len(res) == 2
        assert res[0].d_s < res[1].d_s
        assert res[0].v == pytest.approx(0.7, abs=0.05)
        assert res[1].v == pytest.approx(0.4, abs=0.05)
        assert res[1].rf == pytest.approx(0.5 / 0.8, abs=0.02)

    def test_spot_params_passthrough(self):
        img, bbox = _synth_plate(spots_uv=((0.5, 0.5),))
        # 把 min_area_frac 抬到 1.0 → 应过滤掉所有斑点
        res = rf_measure.analyze_rf(
            img, bbox, origin_frac=0.9, d_f=0.8,
            spot_params={"min_area_frac": 1.0},
        )
        assert res == []
