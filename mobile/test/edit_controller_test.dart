import 'package:adcut_mobile/core/models/api_models.dart';
import 'package:adcut_mobile/features/edit/edit_controller.dart';
import 'package:adcut_mobile/features/edit/variants_controller.dart';
import 'package:adcut_mobile/features/projects/projects_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_backend.dart';
import 'support/harness.dart';

/// Seeds the fake backend with one queued edit and returns its id.
String seedEdit(FakeBackend b, {String instruction = 'Cut to 20 seconds'}) {
  b.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
  final e = b.newEditForTest(instruction);
  return e['id'] as String;
}

void main() {
  test('polls the backend until the edit completes, exposes real stage/progress, then stops', () async {
    final h = await Harness.create();
    final id = seedEdit(h.backend);
    final c = h.container();
    addTearDown(c.dispose);
    final stages = <String?>[];
    c.listen(editControllerProvider(id), (_, s) => stages.add(s.job?.displayStage));

    await until(() => c.read(editControllerProvider(id)).shownVersion != null);

    final s = c.read(editControllerProvider(id));
    expect(s.shownVersion!.outputUrl, FakeBackend.outputUrl);
    expect(stages, contains('Building your edit'));
    final callsAtCompletion = h.backend.getEditCalls;
    await Future<void>.delayed(const Duration(milliseconds: 120));
    expect(h.backend.getEditCalls, callsAtCompletion, reason: 'polling stops on a terminal state');
  });

  test('polling stops when the screen goes away', () async {
    final h = await Harness.create();
    h.backend.stepsToComplete = 1000;
    final id = seedEdit(h.backend);
    final c = h.container();
    final sub = c.listen(editControllerProvider(id), (_, _) {});
    await until(() => h.backend.getEditCalls >= 2);

    sub.close();
    await Future<void>.delayed(const Duration(milliseconds: 30));
    final callsAfterDispose = h.backend.getEditCalls;
    await Future<void>.delayed(const Duration(milliseconds: 120));
    expect(h.backend.getEditCalls, callsAfterDispose);
    c.dispose();
  });

  test('a failed job is reported and not polled again', () async {
    final h = await Harness.create();
    final id = seedEdit(h.backend);
    h.backend.edits[id]!['status'] = 'failed';
    h.backend.edits[id]!['error'] = {'code': 'GENERATION_FAILED', 'message': "We couldn't finish this video."};
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(editControllerProvider(id), (_, _) {});

    await until(() => c.read(editControllerProvider(id)).job != null);

    final s = c.read(editControllerProvider(id));
    expect(s.job!.status, EditStatus.failed);
    expect(s.shownVersion, isNull);
    expect(s.job!.error!.message, isNotEmpty);
    expect(s.isProcessing, isFalse);
  });

  test('losing the network keeps the last state, shows reconnecting, and recovers', () async {
    final h = await Harness.create();
    h.backend.stepsToComplete = 6;
    final id = seedEdit(h.backend);
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(editControllerProvider(id), (_, _) {});
    await until(() => c.read(editControllerProvider(id)).job?.status == EditStatus.running);

    h.backend.failGetEdit = true;
    await until(() => c.read(editControllerProvider(id)).isReconnecting);
    expect(c.read(editControllerProvider(id)).job, isNotNull, reason: 'last known state is kept');

    h.backend.failGetEdit = false;
    await until(() => c.read(editControllerProvider(id)).shownVersion != null);
    expect(c.read(editControllerProvider(id)).isReconnecting, isFalse);
  });

  test('an unknown edit surfaces a load error that can be retried', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(editControllerProvider('nope'), (_, _) {});
    await until(() => c.read(editControllerProvider('nope')).loadError != null);
    expect(c.read(editControllerProvider('nope')).loadError!.code, 'NOT_FOUND');
    expect(c.read(editControllerProvider('nope')).isLoading, isFalse);
  });

  test('a revision creates version 2, keeps version 1 available, and completes', () async {
    final h = await Harness.create();
    final id = seedEdit(h.backend);
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(editControllerProvider(id), (_, _) {});
    await until(() => c.read(editControllerProvider(id)).shownVersion != null);
    final v1 = c.read(editControllerProvider(id)).shownVersion!;

    final ok = await c.read(editControllerProvider(id).notifier).sendInstruction('Make the opening stronger.');
    expect(ok, isTrue);
    expect(h.backend.instructionBodies.single['instruction'], 'Make the opening stronger.');

    await until(() => c.read(editControllerProvider(id)).activeVersion != null);
    expect(
      c.read(editControllerProvider(id)).shownVersion!.id,
      v1.id,
      reason: 'previous result stays visible while revising',
    );

    await until(() => c.read(editControllerProvider(id)).completedVersions.length == 2);
    final s = c.read(editControllerProvider(id));
    expect(s.versions.map((v) => v.version), [1, 2]);
    expect(s.shownVersion!.version, 2);
    expect(s.isProcessing, isFalse);

    c.read(editControllerProvider(id).notifier).selectVersion(v1.id);
    expect(c.read(editControllerProvider(id)).shownVersion!.version, 1);
  });

  test('double-sending an instruction creates a single revision', () async {
    final h = await Harness.create();
    final id = seedEdit(h.backend);
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(editControllerProvider(id), (_, _) {});
    await until(() => c.read(editControllerProvider(id)).shownVersion != null);
    final n = c.read(editControllerProvider(id).notifier);

    final results = await Future.wait([
      n.sendInstruction('Add captions please'),
      n.sendInstruction('Add captions please'),
    ]);

    expect(results.where((r) => r), hasLength(1));
    expect(h.backend.instructionBodies, hasLength(1));
  });

  test('a running edit can be cancelled', () async {
    final h = await Harness.create();
    h.backend.stepsToComplete = 1000;
    final id = seedEdit(h.backend);
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(editControllerProvider(id), (_, _) {});
    await until(() => c.read(editControllerProvider(id)).job != null);

    await c.read(editControllerProvider(id).notifier).cancel();

    expect(c.read(editControllerProvider(id)).job!.status, EditStatus.cancelled);
  });

  test('projects load from the backend, and a failure is an error state that a refresh recovers from', () async {
    final h = await Harness.create();
    seedEdit(h.backend);
    h.backend.failProjects = true;
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(projectsProvider, (_, _) {});
    await until(() => c.read(projectsProvider).hasError);

    h.backend.failProjects = false;
    c.invalidate(projectsProvider);
    await until(() => c.read(projectsProvider).hasValue);
    final p = c.read(projectsProvider).requireValue.single;
    expect(p.name, 'UGC Test');
    expect(p.latestEdit!.id, 'edit-1');
  });

  test('a project list is empty when the user has nothing yet', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(projectsProvider, (_, _) {});
    await until(() => c.read(projectsProvider).hasValue);
    expect(c.read(projectsProvider).requireValue, isEmpty);
  });

  test('variants: creating three shows real hook variants and polls until they finish', () async {
    final h = await Harness.create();
    final id = seedEdit(h.backend);
    h.backend.edits[id]!['status'] = 'completed';
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(variantsControllerProvider(id), (_, _) {});
    await until(() => c.read(variantsControllerProvider(id)).variants != null);
    expect(c.read(variantsControllerProvider(id)).variants, isEmpty);

    final n = c.read(variantsControllerProvider(id).notifier);
    await Future.wait([n.createMore(), n.createMore()]);

    await until(() => c.read(variantsControllerProvider(id)).variants!.length == 3);
    await until(() => c.read(variantsControllerProvider(id)).variants!.every((v) => v.isDone));
    expect(c.read(variantsControllerProvider(id)).variants!.map((v) => v.variant!.label), [
      'Problem Hook',
      'Curiosity Hook',
      'Benefit Hook',
    ]);
    expect(
      h.backend.edits.values.where((e) => e['kind'] == 'variant'),
      hasLength(3),
      reason: 'concurrent taps create one batch',
    );
  });
}
