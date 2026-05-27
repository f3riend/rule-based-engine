<?php
declare(strict_types=1);
/** @var string $approvalsHeading */
/** @var string $approvalsIntro */
$approvalsHeading = $approvalsHeading ?? 'Onay Bekleyenler';
$approvalsIntro = $approvalsIntro ?? 'Onay bekleyen içerikleri görüntüleyin ve yönetin.';
?>
<div id="sm-app" class="sm-studio-embed-host" aria-hidden="true"></div>
<div class="sm-premium-page">
  <header class="sm-premium-page__header">
    <div>
      <h1 class="sm-premium-page__title"><?= htmlspecialchars($approvalsHeading, ENT_QUOTES, 'UTF-8') ?></h1>
      <p class="sm-premium-page__subtitle">
        <?= htmlspecialchars($approvalsIntro, ENT_QUOTES, 'UTF-8') ?>
        Toplam bekleyen: <strong data-approvals-total>0</strong>
      </p>
    </div>
    <button type="button" class="sm-premium-btn sm-premium-btn--primary" data-act="approvals-create">+ Yeni içerik oluştur</button>
  </header>
  <div id="approvals-root"></div>
</div>
