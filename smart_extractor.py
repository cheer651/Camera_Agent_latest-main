from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sklearn.cluster import KMeans


class SmartKeyframeExtractor:
    def __init__(
        self,
        input_video: str,
        output_path: str,
        base_threshold: float = 0.78,
        frame_rate: int = 6,
        scale_factor: float = 0.55,
        min_time_gap: float = 1.0,
        use_clustering: bool = True,
        event_time_gap: float = 2.5,
        event_similarity_threshold: float = 0.45,
        max_event_duration: float = 20.0,
        max_representative_frames: int = 3,
        motion_threshold: float = 1.8,
    ) -> None:
        self.input_video = input_video
        self.output_path = output_path
        self.base_threshold = base_threshold
        self.frame_rate = frame_rate
        self.scale_factor = scale_factor
        self.min_time_gap = min_time_gap
        self.use_clustering = use_clustering
        self.event_time_gap = event_time_gap
        self.event_similarity_threshold = event_similarity_threshold
        self.max_event_duration = max_event_duration
        self.max_representative_frames = max(1, max_representative_frames)
        self.motion_threshold = motion_threshold
        self.person_confidence_threshold = 0.65
        self.person_min_top_ratio = 0.08
        self.person_min_bottom_ratio = 0.55
        self.person_min_height_ratio = 0.30
        self.person_min_area_ratio = 0.03
        self.foreground_area_keep_threshold = 0.012
        self.low_pose_area_threshold = 0.012
        self.low_pose_aspect_threshold = 1.15
        self.low_pose_center_y_threshold = 0.55
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=300,
            varThreshold=24,
            detectShadows=False,
        )

        self.keyframes: list[dict[str, Any]] = []

    @staticmethod
    def _similarity_score(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        image_a = frame_a.astype(np.float64)
        image_b = frame_b.astype(np.float64)

        mean_a = image_a.mean()
        mean_b = image_b.mean()
        var_a = image_a.var()
        var_b = image_b.var()
        covariance = ((image_a - mean_a) * (image_b - mean_b)).mean()

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2
        denominator = (mean_a**2 + mean_b**2 + c1) * (var_a + var_b + c2)
        if denominator == 0:
            return 1.0

        score = ((2 * mean_a * mean_b + c1) * (2 * covariance + c2)) / denominator
        return float(max(0.0, min(1.0, score)))

    def run(self) -> dict[str, Any] | None:
        cap = cv2.VideoCapture(self.input_video)
        if not cap.isOpened():
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 24.0

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0.0
        frame_interval = max(1, int(round(fps / max(self.frame_rate, 1))))
        min_frame_gap = max(1, int(round(self.min_time_gap * fps)))

        last_keyframe_gray: np.ndarray | None = None
        last_keyframe_index = -min_frame_gap
        previous_sample_signature: np.ndarray | None = None
        frame_index = 0

        try:
            while True:
                success, frame = cap.read()
                if not success:
                    break

                if frame_index % frame_interval != 0:
                    frame_index += 1
                    continue

                signature = self._build_signature(frame)
                person_count, person_score = self._detect_people(frame)
                motion_features = self._extract_motion_features(frame)
                motion_score = (
                    self._motion_score(previous_sample_signature, signature)
                    if previous_sample_signature is not None
                    else 0.0
                )

                should_keep = False
                similarity = 1.0
                if last_keyframe_gray is None:
                    if (
                        person_count > 0
                        or bool(motion_features.get("low_pose_candidate", False))
                        or float(motion_features.get("foreground_area_ratio", 0.0)) >= self.foreground_area_keep_threshold
                    ):
                        should_keep = True
                    else:
                        last_keyframe_gray = signature
                        last_keyframe_index = frame_index
                elif frame_index - last_keyframe_index >= min_frame_gap:
                    similarity = self._similarity_score(last_keyframe_gray, signature)
                    if person_count > 0:
                        should_keep = True
                    elif bool(motion_features.get("low_pose_candidate", False)):
                        should_keep = True
                    elif float(motion_features.get("foreground_area_ratio", 0.0)) >= self.foreground_area_keep_threshold:
                        should_keep = True
                    elif similarity < self.base_threshold or motion_score >= self.motion_threshold:
                        should_keep = True

                if should_keep:
                    self.keyframes.append(
                        {
                            "frame_index": frame_index,
                            "frame": frame.copy(),
                            "signature": signature,
                            "motion_score": float(motion_score),
                            "similarity_to_last_keyframe": float(similarity),
                            "person_count": int(person_count),
                            "person_score": float(person_score),
                            "foreground_area_ratio": float(motion_features.get("foreground_area_ratio", 0.0)),
                            "foreground_bbox": motion_features.get("foreground_bbox"),
                            "low_pose_candidate": bool(motion_features.get("low_pose_candidate", False)),
                            "low_pose_score": float(motion_features.get("low_pose_score", 0.0)),
                        }
                    )
                    last_keyframe_gray = signature
                    last_keyframe_index = frame_index

                previous_sample_signature = signature
                frame_index += 1
        finally:
            cap.release()

        if self.use_clustering and len(self.keyframes) > 15:
            self._apply_clustering()

        event_groups = self._build_event_groups(fps)
        event_groups = self._filter_event_groups(event_groups)
        saved_frames = self._save_event_representatives(event_groups)
        return {
            "duration": round(duration, 2),
            "fps": round(fps, 2),
            "total_frames": total_frames,
            "extracted_count": len(self.keyframes),
            "event_count": len(event_groups),
            "representative_count": len(saved_frames),
            "frames": saved_frames,
        }

    def _build_signature(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(
            gray,
            (max(1, int(gray.shape[1] * self.scale_factor)), max(1, int(gray.shape[0] * self.scale_factor))),
        )

    @staticmethod
    def _motion_score(previous_signature: np.ndarray | None, current_signature: np.ndarray) -> float:
        if previous_signature is None:
            return 0.0
        diff = cv2.absdiff(previous_signature, current_signature)
        return float(diff.mean())

    def _extract_motion_features(self, frame: np.ndarray) -> dict[str, Any]:
        mask = self.background_subtractor.apply(frame)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        frame_height, frame_width = frame.shape[:2]
        frame_area = float(max(frame_height * frame_width, 1))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        largest_area = 0.0
        largest_bbox: tuple[int, int, int, int] | None = None
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area <= largest_area:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            largest_area = area
            largest_bbox = (int(x), int(y), int(width), int(height))

        foreground_area_ratio = largest_area / frame_area if largest_area > 0 else 0.0
        low_pose_candidate = False
        low_pose_score = 0.0
        if largest_bbox is not None:
            x, y, width, height = largest_bbox
            aspect_ratio = width / max(height, 1)
            center_y_ratio = (y + height / 2.0) / max(frame_height, 1)
            if (
                foreground_area_ratio >= self.low_pose_area_threshold
                and aspect_ratio >= self.low_pose_aspect_threshold
                and center_y_ratio >= self.low_pose_center_y_threshold
            ):
                low_pose_candidate = True
                low_pose_score = foreground_area_ratio * max(aspect_ratio, 1.0) * center_y_ratio

        return {
            "foreground_area_ratio": float(foreground_area_ratio),
            "foreground_bbox": largest_bbox,
            "low_pose_candidate": bool(low_pose_candidate),
            "low_pose_score": float(low_pose_score),
        }

    def _detect_people(self, frame: np.ndarray) -> tuple[int, float]:
        rects, weights = self.hog.detectMultiScale(
            frame,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        frame_height, frame_width = frame.shape[:2]
        valid_weights: list[float] = []
        for rect, weight in zip(rects, weights):
            x, y, width, height = [int(value) for value in rect]
            top_ratio = y / max(frame_height, 1)
            bottom_ratio = (y + height) / max(frame_height, 1)
            height_ratio = height / max(frame_height, 1)
            area_ratio = (width * height) / max(frame_height * frame_width, 1)
            if float(weight) < self.person_confidence_threshold:
                continue
            if top_ratio < self.person_min_top_ratio:
                continue
            if bottom_ratio < self.person_min_bottom_ratio:
                continue
            if height_ratio < self.person_min_height_ratio:
                continue
            if area_ratio < self.person_min_area_ratio:
                continue
            valid_weights.append(float(weight))

        return len(valid_weights), (max(valid_weights) if valid_weights else 0.0)

    def _apply_clustering(self) -> None:
        features = []
        for item in self.keyframes:
            small = cv2.resize(item["frame"], (64, 64))
            features.append(small.flatten())

        if not features:
            return

        cluster_count = min(20, max(3, len(self.keyframes) // 3))
        labels = KMeans(n_clusters=cluster_count, n_init=5, random_state=42).fit_predict(features)

        reduced: list[dict[str, Any]] = []
        seen_labels: set[int] = set()
        priority_frames = [
            item
            for item in self.keyframes
            if int(item.get("person_count", 0)) > 0 or bool(item.get("low_pose_candidate", False))
        ]
        for index, label in enumerate(labels):
            if int(label) not in seen_labels:
                reduced.append(self.keyframes[index])
                seen_labels.add(int(label))

        for item in priority_frames:
            if not any(int(existing["frame_index"]) == int(item["frame_index"]) for existing in reduced):
                reduced.append(item)

        reduced.sort(key=lambda item: int(item["frame_index"]))
        self.keyframes = reduced

    def _build_event_groups(self, fps: float) -> list[dict[str, Any]]:
        if not self.keyframes:
            return []

        prepared_frames: list[dict[str, Any]] = []
        for item in self.keyframes:
            second = round(int(item["frame_index"]) / fps, 2) if fps > 0 else 0.0
            prepared_frames.append(
                {
                    "frame_index": int(item["frame_index"]),
                    "second": second,
                    "frame": item["frame"],
                    "signature": item["signature"],
                    "motion_score": float(item.get("motion_score", 0.0)),
                    "person_count": int(item.get("person_count", 0)),
                    "person_score": float(item.get("person_score", 0.0)),
                    "foreground_area_ratio": float(item.get("foreground_area_ratio", 0.0)),
                    "low_pose_candidate": bool(item.get("low_pose_candidate", False)),
                    "low_pose_score": float(item.get("low_pose_score", 0.0)),
                }
            )

        groups: list[dict[str, Any]] = []
        current_group: dict[str, Any] | None = None
        tight_gap = min(1.2, self.event_time_gap)

        for frame in prepared_frames:
            if current_group is None:
                current_group = {
                    "start_second": float(frame["second"]),
                    "end_second": float(frame["second"]),
                    "frames": [frame],
                }
                continue

            previous_frame = current_group["frames"][-1]
            time_gap = float(frame["second"]) - float(previous_frame["second"])
            duration = float(frame["second"]) - float(current_group["start_second"])
            similarity = self._similarity_score(previous_frame["signature"], frame["signature"])

            same_event = duration <= self.max_event_duration and (
                time_gap <= tight_gap
                or (time_gap <= self.event_time_gap and similarity >= self.event_similarity_threshold)
            )

            if same_event:
                current_group["frames"].append(frame)
                current_group["end_second"] = float(frame["second"])
            else:
                groups.append(current_group)
                current_group = {
                    "start_second": float(frame["second"]),
                    "end_second": float(frame["second"]),
                    "frames": [frame],
                }

        if current_group is not None:
            groups.append(current_group)

        for index, group in enumerate(groups, start=1):
            group["event_group_id"] = f"event_{index:03d}"
            group["duration_seconds"] = round(float(group["end_second"]) - float(group["start_second"]), 2)
            group["frame_count"] = len(group["frames"])
            group["representative_indices"] = self._select_representative_indices(group["frames"])

        return groups

    def _filter_event_groups(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for group in groups:
            frames = list(group.get("frames", []))
            if not frames:
                continue
            person_frames = sum(1 for frame in frames if int(frame.get("person_count", 0)) > 0)
            low_pose_frames = sum(1 for frame in frames if bool(frame.get("low_pose_candidate", False)))
            max_motion = max(float(frame.get("motion_score", 0.0)) for frame in frames)
            max_foreground_area = max(float(frame.get("foreground_area_ratio", 0.0)) for frame in frames)
            frame_count = int(group.get("frame_count", len(frames)))
            if person_frames > 0:
                filtered.append(group)
                continue
            if low_pose_frames > 0:
                filtered.append(group)
                continue
            if frame_count >= 2 and max_motion >= self.motion_threshold * 4:
                filtered.append(group)
                continue
            if frame_count >= 2 and max_foreground_area >= self.foreground_area_keep_threshold * 1.5:
                filtered.append(group)

        for index, group in enumerate(filtered, start=1):
            group["event_group_id"] = f"event_{index:03d}"
            group["duration_seconds"] = round(float(group["end_second"]) - float(group["start_second"]), 2)
            group["frame_count"] = len(group["frames"])
            group["representative_indices"] = self._select_representative_indices(group["frames"])

        return filtered

    def _select_representative_indices(self, frames: list[dict[str, Any]]) -> list[int]:
        if not frames:
            return []

        total = len(frames)
        ranked = sorted(
            range(total),
            key=lambda idx: (
                int(bool(frames[idx].get("low_pose_candidate", False))),
                float(frames[idx].get("low_pose_score", 0.0)),
                int(frames[idx].get("person_count", 0) > 0),
                float(frames[idx].get("person_score", 0.0)),
                float(frames[idx].get("motion_score", 0.0)),
                float(frames[idx].get("foreground_area_ratio", 0.0)),
            ),
            reverse=True,
        )

        low_pose_indices = [idx for idx in ranked if bool(frames[idx].get("low_pose_candidate", False))]
        person_indices = [idx for idx in ranked if int(frames[idx].get("person_count", 0)) > 0]
        anchors: list[int] = []

        if low_pose_indices:
            anchors.append(low_pose_indices[0])
            settled_low_pose = max(
                low_pose_indices,
                key=lambda idx: (
                    float(frames[idx].get("foreground_area_ratio", 0.0)),
                    int(frames[idx].get("frame_index", 0)),
                ),
            )
            if settled_low_pose not in anchors:
                anchors.append(settled_low_pose)
        elif person_indices:
            anchors.append(person_indices[0])

        peak_motion_index = max(range(total), key=lambda idx: float(frames[idx].get("motion_score", 0.0)))
        if peak_motion_index not in anchors:
            anchors.append(peak_motion_index)

        selected: list[int] = []
        for idx in anchors + ranked:
            if idx not in selected:
                selected.append(idx)
            if len(selected) >= self.max_representative_frames:
                break

        if not selected:
            selected = [peak_motion_index]
        return sorted(selected)

    def _save_event_representatives(self, event_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        save_dir = Path(self.output_path) / "extracted_frames"
        save_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        for group in event_groups:
            representative_indices = list(group.get("representative_indices", []))
            representative_total = len(representative_indices)
            primary_index = (
                max(
                    representative_indices,
                    key=lambda idx: (
                        int(group["frames"][idx].get("person_count", 0) > 0),
                        float(group["frames"][idx].get("person_score", 0.0)),
                        float(group["frames"][idx].get("motion_score", 0.0)),
                    ),
                )
                if representative_indices
                else 0
            )

            for rank, frame_index in enumerate(representative_indices, start=1):
                frame_record = group["frames"][frame_index]
                second = float(frame_record["second"])
                filename = (
                    f"{group['event_group_id']}_rep_{rank:02d}_sec{second:06.2f}.jpg"
                )
                filepath = save_dir / filename
                cv2.imwrite(str(filepath), frame_record["frame"])
                results.append(
                    {
                        "filename": filename,
                        "filepath": str(filepath),
                        "frame_index": int(frame_record["frame_index"]),
                        "second": second,
                        "event_group_id": str(group["event_group_id"]),
                        "event_frame_count": int(group["frame_count"]),
                        "representative_count": representative_total,
                        "event_start_second": float(group["start_second"]),
                        "event_end_second": float(group["end_second"]),
                        "event_duration_seconds": float(group["duration_seconds"]),
                        "representative_rank": rank,
                        "is_primary": int(frame_index == primary_index),
                        "person_count_hint": int(frame_record.get("person_count", 0)),
                        "person_score_hint": float(frame_record.get("person_score", 0.0)),
                        "low_pose_hint": int(bool(frame_record.get("low_pose_candidate", False))),
                        "foreground_area_ratio_hint": float(frame_record.get("foreground_area_ratio", 0.0)),
                    }
                )
        return results
